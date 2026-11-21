"""Phenom-Karriereportale (z. B. Deutsche Post / DHL): Suche über die Widget-Schnittstelle des Portals.

Die Suchergebnisse stehen bei diesen Portalen nicht im HTML, sondern werden vom Browser per
`POST https://<Host>/widgets` (JSON, Sitzungs-Cookie, Header `X-CSRF-Token`) nachgeladen. Der Leser macht dasselbe:
1. `GET <Host>/<Sprache>/search-results?keywords=…` liefert Cookie, `csrfToken` und `pageId` der Seite (und bei
   manchen Portalen, z. B. Catalent, schon die ersten Treffer als `phApp.ddo.eagerLoadRefineSearch`).
2. `POST /widgets` mit der Suchanfrage (`ddoKey: refineSearch`, Suchbegriff, Ort als `locationData` mit Koordinaten
   und Radius, Sprache/Land aus `"locale"` der Seite, Seitenwechsel über `from`), Antwort
   `refineSearch.data.jobs[]` mit Titel, Ort (Stadt, Land, Koordinaten), Datum, Kurztext und Kennung.
Die Anzeigenadresse ist `https://<Host>/<Sprache>/job/<Kennung>/<Titel-Slug>`; Einzelseiten werden nicht abgerufen.
Jede Anzeige läuft durch dieselbe Prüfung wie ein JobPosting (`extract`). Der Leser ist in `sources.py` an die
bekannten Portale (`PHENOM_TENANTS`) gebunden.
"""
import json
import re
from urllib.parse import quote

import geo
from extraction import extract
from safe_http import FetchError
from sources import PHENOM_TENANTS

PAGE = 10  # Seitengröße des Portals (wie im Browser)
MAX_PAGES = 8
GERMANY = {"germany", "deutschland", "de"}
FIELDS = ["category", "country", "state", "city", "type"]


def slug(title):
    """Wie die Portale den Titel in die Adresse setzen: alles außer Buchstaben/Ziffern wird zu „-“."""
    return re.sub(r"[\W_]+", "-", title, flags=re.UNICODE).strip("-")


def search_url(tenant, query):
    return f"https://{tenant['host']}/{tenant['locale']}/search-results?keywords={quote(query, safe='')}"


def payload(lang, country, page_id, query, offset, fields, location=None):
    """Suchanfrage wie die Seite selbst (Parameter so, wie das Portal sie in `eagerLoadRefineSearch` zurückmeldet)."""
    body = {"lang": lang, "deviceType": "desktop", "country": country, "pageName": "search-results",
            "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": offset, "jobs": True, "counts": True,
            "all_fields": fields, "size": PAGE, "clearAll": False, "jdsource": "facets", "isSliderEnable": bool(location),
            "pageId": page_id, "siteType": "external", "keywords": query, "global": True, "selected_fields": {},
            "locationData": {}}
    if location:
        (lat, lon), place, radius = location
        body["locationData"] = {"place_id": "", "latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}", "aboveMaxRadius": False,
                                "placeVal": place, "sliderRadius": int(radius), "LocationUnit": "kilometers"}
    return body


def page_locale(html, tenant):
    """Sprache/Land des Portals aus der Seite (`"locale":"de_eu"` → lang de_eu, country eu), sonst aus der Bindung."""
    found = re.search(r'"locale"\s*:\s*"([a-z]{2})_([a-z]{2,4})"', html)
    return (f"{found[1]}_{found[2]}", found[2]) if found else (tenant["lang"], tenant["country"])


def facet_fields(eager):
    data = eager.get("data") if isinstance(eager, dict) else None
    names = [a.get("field") for a in (data or {}).get("aggregations") or [] if isinstance(a, dict)]
    names = [n for n in names if isinstance(n, str) and re.fullmatch(r"[A-Za-z]{2,30}", n)]
    return names[:12] or FIELDS


def eager_result(html):
    """Erste Treffer, die manche Portale (z. B. Catalent) schon in der Seite mitliefern: `phApp.ddo.eagerLoadRefineSearch`."""
    marker = "phApp.ddo = "
    start = html.find(marker)
    if start < 0:
        return None
    try:
        ddo, _ = json.JSONDecoder().raw_decode(html, start + len(marker))
    except ValueError:
        return None
    result = ddo.get("eagerLoadRefineSearch") if isinstance(ddo, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict) or not isinstance(result.get("totalHits"), int):
        return None
    return result


def classify(tenant, row):
    """(Datensatz, Grund): Grund ist None bei brauchbaren Treffern, sonst „kennung“ oder „land:<Wert>“."""
    if not isinstance(row, dict):
        return None, "kennung"
    ident, title = row.get(tenant["id_field"]), row.get("title")
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9]{3,60}", ident) or not isinstance(title, str) or not slug(title):
        return None, "kennung"
    country = str(row.get("country") or "")
    if country.casefold() not in GERMANY:
        return None, "land:" + (country or "leer")
    address = {"@type": "PostalAddress", "addressLocality": str(row.get("city") or ""),
               "addressRegion": str(row.get("state") or ""), "addressCountry": "DE"}
    url = f"https://{tenant['host']}/{tenant['locale']}/job/{ident}/{quote(slug(title), safe='-')}"
    data = {"@type": "JobPosting", "title": title, "url": url, "hiringOrganization": {"name": tenant["company"]},
            "jobLocation": {"@type": "Place", "address": address}, "datePosted": str(row.get("postedDate") or "")[:10]}
    if isinstance(row.get("descriptionTeaser"), str):
        data["description"] = row["descriptionTeaser"][:4000]
    return data, None


def record(tenant, row):
    """JobPosting-artiger Datensatz aus einem Treffer, nur mit belegten Feldern; None wenn Pflichtfelder fehlen."""
    return classify(tenant, row)[0]


def coordinates(row):
    try:
        return float(row["latitude"]), float(row["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def phenom(source, req, get, report):
    tenant = PHENOM_TENANTS[source.key]
    cookies = {}
    page_url = search_url(tenant, req.q)
    _, html = get(page_url, source, cookies=cookies)
    token = re.search(r'"csrfToken"\s*:\s*"([A-Za-z0-9-]{8,80})"', html)
    page = re.search(r'phApp\.pageId\s*=\s*"([A-Za-z0-9_-]{1,40})"', html) or re.search(r'"pageId"\s*:\s*"([A-Za-z0-9_-]{1,40})"', html)
    if not token or not page:
        raise FetchError("unsupported", detail=f"kein csrfToken/pageId auf {page_url} ({len(html)} Zeichen, Cookies {len(cookies)})")
    headers = {"X-CSRF-Token": token[1], "Referer": page_url, "Origin": f"https://{tenant['host']}"}
    widgets = f"https://{tenant['host']}/widgets"
    lang, country = page_locale(html, tenant)
    eager = eager_result(html)
    fields = facet_fields(eager)
    origin = geo.center(req.location) if getattr(req, "location", "") else None
    radius = getattr(req, "radius_km", 25)
    location = (origin, req.location, radius) if origin else None

    def search(offset):
        _, text = get(widgets, source, accept_json=True, json_body=payload(lang, country, page[1], req.q, offset, fields, location),
                      cookies=cookies, extra_headers=headers)
        try:
            body = json.loads(text)
        except ValueError:
            raise FetchError("unsupported", detail="Widget-Antwort ist kein JSON") from None
        result = body.get("refineSearch") if isinstance(body, dict) else None
        if not isinstance(result, dict) or result.get("status") not in (200, "200", None) or not isinstance(result.get("data"), dict):
            raise FetchError("unsupported", detail="Widget-Antwort ohne Treffer-Daten: " + json.dumps(body)[:160])
        return result

    rows, sizes, total, source_note = [], [], 0, "Suche"
    try:
        result = search(0)
        total = result.get("totalHits") if isinstance(result.get("totalHits"), int) else 0
        rows = list(result["data"].get("jobs") or [])
        sizes.append(len(rows))
        while rows and len(rows) < min(total, PAGE * MAX_PAGES):
            batch = search(len(rows))["data"].get("jobs") or []
            sizes.append(len(batch))
            if not batch:
                break
            rows.extend(batch)
    except FetchError as error:
        # Die eingebetteten Treffer der Seite kennen weder Suchbegriff noch Ort; sie sind nur der Notbehelf.
        if eager is None or rows:
            if not rows:
                raise
        else:
            rows = list(eager["data"].get("jobs") or [])
            total = eager.get("totalHits") or len(rows)
            source_note = f"eingebettete Seite, Suche fehlgeschlagen: {error.detail or error.code}"
    ranked, why, foreign = [], {"kennung": 0, "umkreis": 0}, {}
    for row in rows:
        data, reason = classify(tenant, row)
        if not data:
            if reason == "kennung":
                why["kennung"] += 1
            else:
                foreign[reason[5:]] = foreign.get(reason[5:], 0) + 1
            continue
        point = coordinates(row)
        near = geo.km(origin, point) if origin and point else (
            geo.distance_km(origin, data["jobLocation"]["address"]["addressLocality"]) if origin else None)
        if near is not None and near > radius:
            why["umkreis"] += 1
            continue
        ranked.append((near is None, near or 0, data))
    if not ranked or total > len(rows):
        top = ", ".join(f"{name}×{count}" for name, count in sorted(foreign.items(), key=lambda kv: -kv[1])[:4]) or "-"
        report["detail"] = (
            f"{total} Treffer ({source_note}, {lang}, Ort {'ja' if location else 'nein'}), {len(rows)} gelesen (Seiten {sizes}); "
            f"{len(ranked)} in Deutschland und im Umkreis; anderes Land: {top}; ohne Kennung {why['kennung']}; "
            f"außerhalb Umkreis {why['umkreis']}")
    ranked.sort(key=lambda item: (item[0], item[1]))
    for _, _, data in ranked:
        safe = json.dumps(data).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + safe + "</script>", data["url"], source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
