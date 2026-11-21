"""Ortsfilter für jobsucheBW (Nussbaum Medien) schon in der Suche statt erst nach den Einzelanzeigen.

Die Suche /suchergebnis/ filtert serverseitig nach Umkreis, braucht dafür aber die interne locationId des Portals
(z. B. Waiblingen = M-DE-1427). Die Ortsseite /stellenangebote/<ort>/ löst den Namen auf und nennt die ID in ihren
Seitendaten (requests.locationInfo). Gelingt das nicht, bleibt nur die bundesweite Liste – dann zählen die
Koordinaten, die die Trefferliste zu jeder Anzeige mitliefert (jobAd.geo), bevor eine Einzelanzeige abgerufen wird.
"""
import json
import re
from urllib.parse import quote

import geo

ORIGIN = "https://www.jobsuche-bw.de"
# Umkreisstufen des Portals (Filter „Entfernung“).
RADII = (20, 30, 40, 50, 75, 100, 200)
_ID = re.compile(r"/jobs/((?:[A-Z]{3}-)?\d+)/")


def place_name(text):
    """Ortsname aus der Suchangabe: „71332 Waiblingen“, „Waiblingen, BW“ oder nur eine Postleitzahl."""
    text = (text or "").strip()
    name = re.sub(r"\b\d{5}\b", " ", text.split(",")[0])
    name = " ".join(name.split())
    if name:
        return name
    if code := re.search(r"\b\d{5}\b", text):
        return geo.name_for_postcode(code.group(0))
    return None


def slug(name):
    value = name.lower()
    for char, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        value = value.replace(char, replacement)
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def radius_option(km):
    """Kleinste Portalstufe, die den gewünschten Umkreis abdeckt (Feinfilter folgt pro Anzeige)."""
    return next((value for value in RADII if value >= km), RADII[-1])


def _flight(html):
    """Seitendaten der Next.js-Seite; im HTML als JSON-Text mit maskierten Anführungszeichen."""
    return html.replace('\\"', '"')


def location_of(html):
    """(locationId, (lat, lng)) der aufgelösten Ortsseite oder None."""
    data = _flight(html)
    match = re.search(r'"locationInfo":\{"locations":\[\{"locationId":"([A-Z]-DE[A-Za-z0-9-]*)"(.{0,600}?)\}', data)
    if not match:
        return None
    lat = re.search(r'"latitude":(-?\d+(?:\.\d+)?)', match.group(2))
    lng = re.search(r'"longitude":(-?\d+(?:\.\d+)?)', match.group(2))
    return match.group(1), ((float(lat.group(1)), float(lng.group(1))) if lat and lng else None)


def listing_points(html):
    """Anzeigen-ID → Koordinaten aller Standorte aus der Trefferliste (jobAd.geo vor jobAd.id)."""
    points = {}
    for match in re.finditer(r'"geo":(\[[^\]]*\]),"id":"((?:[A-Z]{3}-)?\d+)"', _flight(html)):
        try:
            rows = json.loads(match.group(1))
            sites = [(float(row["lat"]), float(row["lng"])) for row in rows if isinstance(row, dict)]
        except (ValueError, KeyError, TypeError):
            continue
        if sites:
            points.setdefault(match.group(2), []).extend(sites)
    return points


def ad_id(url):
    match = _ID.search(url + "/")
    return match.group(1) if match else None


def plan(req, source, allowed_get, report):
    """Start-URL und Mittelpunkt für den Listenfilter. Kostet bei gesetztem Ort einen Dokumentabruf."""
    from safe_http import FetchError

    fulltext = quote(req.q, safe="")
    bundesweit = f"{ORIGIN}/suchergebnis/?fulltext={fulltext}"
    if not req.location:
        return bundesweit, None
    origin = geo.center(req.location)
    name = place_name(req.location)
    resolved = None
    if name and slug(name):
        try:
            _, html = allowed_get(f"{ORIGIN}/stellenangebote/{slug(name)}/", source)
            resolved = location_of(html)
        except FetchError as error:
            if error.code in {"timeout", "blocked", "request_limit"}:
                raise
    if resolved:
        location_id, point = resolved
        report["location_filter"] = "Portal-Umkreissuche"
        start = (f"{ORIGIN}/suchergebnis/?fulltext={fulltext}&locationId={quote(location_id, safe='')}"
                 f"&perimeterRadius={radius_option(req.radius_km)}")
        return start, origin or point
    report["location_filter"] = "Trefferliste nach Koordinaten"
    report["detail"] = (f"Ort „{req.location}“ bei jobsucheBW nicht auflösbar; bundesweite Trefferliste, "
                        "abgerufen werden nur Anzeigen mit Koordinaten im Umkreis.")
    return bundesweit, origin


def keep(links, html, origin, radius_km):
    """Nur Anzeigen, deren Listenkoordinaten im Umkreis liegen. Ohne Koordinaten: nicht abrufen.

    Liefert die Seite gar keine Koordinaten (geändertes Format), bleibt die Liste unverändert; der strenge
    Ortsfilter auf die Einzelanzeige greift dann weiterhin.
    """
    points = listing_points(html) if origin is not None else {}
    if not points:
        return links, 0
    kept, dropped = [], 0
    for link in links:
        sites = points.get(ad_id(link) or "")
        if sites and min(geo.km(origin, site) for site in sites) <= radius_km:
            kept.append(link)
        else:
            dropped += 1
    return kept, dropped
