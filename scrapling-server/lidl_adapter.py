"""Lidl Karriereportal (jobs.lidl.de): Anzeigenliste über die öffentliche Jobs-Sitemap.

Das Portal ist eine Single-Page-App: Startseite und Suche enthalten keine Anzeigenlinks, die Suche läuft per
JavaScript. Die in der robots.txt genannte Sitemap `sitemap-jobs.xml` führt dagegen alle Anzeigen
(`/jobs/<titel>-m-w-d-<ort>-<id>`, rund 15 000, 2,4 MB; dafür erlaubt `Transport.get(accept_xml=True, max_body=…)`
bis 8 MB). Daraus werden Treffer nach Titelwörtern und Entfernung (Ort aus dem Adressnamen, `geo.py`) gewählt; nur
diese Einzelanzeigen werden abgerufen und wie jedes JobPosting geprüft (Arbeitgeber, Ablaufdatum, Relevanz). Die
Einzelanzeige trägt Ort, PLZ und Koordinaten; die genaue Umkreisprüfung passiert danach in der App.
"""
import re

import geo
from employer_adapters import detail_document
from extraction import extract
from persona_adapter import GENDER
from safe_http import FetchError

MAX_SITEMAP = 6 * 1024 * 1024
ENTRY = re.compile(r"<url>(.*?)</url>", re.S)
SLUG = r"([a-z0-9.-]{3,200}-(\d{3,9}))"
LASTMOD = re.compile(r"<lastmod>\s*([0-9T:.+Z-]{10,40})\s*</lastmod>")


def entries(text, host="jobs.lidl.de"):
    """(Titelteil, Ortsteil, URL, Änderungsdatum) je Anzeige; URLs ohne endende Anzeigen-ID zählen nicht.

    Dieselbe Plattform (`/jobs/<titel>-<ort>-<id>`, Sitemap `sitemap-jobs.xml`) nutzen Lidl und Kaufland (Schwarz-Gruppe)."""
    if "<urlset" not in text[:2000]:
        raise FetchError("unsupported", detail="Kein Sitemap")
    loc = re.compile(r"<loc>\s*https://" + re.escape(host) + r"/jobs/" + SLUG + r"\s*</loc>")
    rows = []
    for block in ENTRY.findall(text):
        match = loc.search(block)
        if not match:
            continue
        slug, ident = match.groups()
        body = slug[: -len(ident) - 1]
        parts = GENDER.split(body)
        title, place = (body, "") if len(parts) < 2 else ("-".join(parts[:-1]), parts[-1].strip("-"))
        stamp = LASTMOD.search(block)
        rows.append((title, place, f"https://{host}/jobs/{slug}", stamp.group(1) if stamp else ""))
    return rows


def place_distance(origin, place):
    """Entfernung zum Ort aus dem Adressnamen; bei mehrwortigen Orten erst ganz, dann ohne letztes/erstes Wort."""
    words = [w for w in place.split("-") if w]
    for candidate in (words, words[:-1], words[1:]):
        if candidate:
            distance = geo.distance_km(origin, " ".join(candidate))
            if distance is not None:
                return distance
    return None


def tail_distance(origin, title):
    """Anzeigen ohne Geschlechtsmarker („…-controlling-international-neckarsulm“): Ort aus den letzten 1–3 Wörtern."""
    words = [w for w in title.split("-") if w]
    for size in (3, 2, 1):
        if len(words) > size:
            distance = geo.distance_km(origin, " ".join(words[-size:]))
            if distance is not None:
                return distance
    return None


def select(rows, query, origin, radius):
    terms = [geo.norm(term) for term in query.split() if len(term) >= 2]
    chosen = []
    for title, place, url, stamp in rows:
        score = sum(term in geo.norm(title) for term in terms) if terms else 1
        if not score:
            continue
        distance = (place_distance(origin, place) if place else tail_distance(origin, title)) if origin else None
        if distance is not None and distance > radius:
            continue
        chosen.append((score, distance, url, stamp))
    chosen.sort(key=lambda row: row[3], reverse=True)  # newest first, stable for the keys below
    chosen.sort(key=lambda row: (-row[0], row[1] is None, row[1] or 0))
    return [row[2] for row in chosen]


def lidl(source, req, get, report):
    _, text = get(source.api, source, accept_xml=True, max_body=MAX_SITEMAP)
    rows = entries(text, source.hosts[0])
    origin = geo.center(req.location) if getattr(req, "location", "") else None
    urls = select(rows, req.q, origin, getattr(req, "radius_km", 25))
    report["detail"] = f"{len(rows)} Anzeigen im Sitemap, {len(urls)} passend"
    for raw in urls[:source.max_details]:
        document = detail_document(get, raw, source, report)
        if document is None:
            continue
        final, html = document
        job = extract(html, final, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
