"""persona service Jobbörse (persona.de): Anzeigenliste über das öffentliche Sitemap.

Die Jobbörse ist eine LiveView-Seite: Seitenwechsel und Suchfelder laufen über Websocket-Ereignisse, die URL kennt
weder Suchbegriff noch Umkreis, und im HTML stehen nur 25 von rund 4600 Anzeigen. Das in der robots.txt genannte
`sitemap-de.xml` enthält dagegen alle Anzeigen-URLs `/jobs/<titel>-m-w-d-<ort>/<uuid>` samt Änderungsdatum.
Daraus werden Treffer nach Titel und (wenn bekannt) Ortsentfernung ausgewählt; nur diese Einzelanzeigen werden
abgerufen und wie jedes JobPosting geprüft (Arbeitgeber, Ablaufdatum, Relevanz). Die Einzelanzeige trägt Ort und PLZ,
die genaue Umkreisprüfung passiert danach in der App.
"""
import re

import geo
from employer_adapters import detail_document
from extraction import extract
from safe_http import FetchError

SITEMAP = "https://www.persona.de/sitemap-de.xml"
MAX_SITEMAP = 6 * 1024 * 1024
ENTRY = re.compile(r"<url>(.*?)</url>", re.S)
LOC = re.compile(r"<loc>\s*https://www\.persona\.de/jobs/([a-z0-9-]{3,200})/"
                 r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*</loc>")
LASTMOD = re.compile(r"<lastmod>\s*([0-9T:.+Z-]{10,40})\s*</lastmod>")
GENDER = re.compile(r"-(?:m-w-d|w-m-d|m-f-d|f-m-d|m-w-x)(?=-|$)")


def entries(text):
    """(Titelteil, Ortsteil, URL, Änderungsdatum) je Anzeige; Anzeigen anderer Sprachen und Bereiche zählen nicht."""
    if "<urlset" not in text[:2000]:
        raise FetchError("unsupported", detail="Kein Sitemap: " + " ".join(text[:80].split()))
    rows = []
    for block in ENTRY.findall(text):
        match = LOC.search(block)
        if not match:
            continue
        slug, ident = match.groups()
        parts = GENDER.split(slug)
        title, place = (GENDER.sub("", slug), "") if len(parts) < 2 else ("-".join(parts[:-1]), parts[-1].strip("-"))
        stamp = LASTMOD.search(block)
        rows.append((title, place, f"https://www.persona.de/jobs/{slug}/{ident}", stamp.group(1) if stamp else ""))
    return rows


def select(rows, query, origin, radius):
    terms = [geo.norm(term) for term in query.split() if len(term) >= 2]
    chosen = []
    for title, place, url, stamp in rows:
        # Ohne Suchbegriff (Katalog-Lauf) zählt jede Anzeige; gefiltert wird erst in der App.
        score = sum(term in geo.norm(title) for term in terms) if terms else 1
        if not score:
            continue
        distance = geo.distance_km(origin, place.replace("-", " ")) if origin and place else None
        if distance is not None and distance > radius:
            continue
        chosen.append((score, distance, url, stamp))
    chosen.sort(key=lambda row: row[3], reverse=True)  # newest first, stable for the keys below
    chosen.sort(key=lambda row: (-row[0], row[1] is None, row[1] or 0))
    return [row[2] for row in chosen]


def persona(source, req, get, report):
    _, text = get(source.api, source, accept_xml=True, max_body=MAX_SITEMAP)
    rows = entries(text)
    origin = geo.center(req.location) if getattr(req, "location", "") else None
    urls = select(rows, req.q, origin, getattr(req, "radius_km", 25))
    report["detail"] = f"{len(rows)} Anzeigen im Sitemap, {len(urls)} passend"
    for raw in urls[:getattr(req, "max_details", source.max_details)]:
        document = detail_document(get, raw, source, report)
        if document is None:
            continue
        final, html = document
        job = extract(html, final, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
