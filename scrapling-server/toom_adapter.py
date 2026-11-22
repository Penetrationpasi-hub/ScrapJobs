"""toom: öffentliche Umkreissuche und verlinkte Originalanzeigen bei d.vinci.

Die Karriereseite schreibt ihren Importzeitpunkt in validThrough. Deshalb werden
die Original-JobPostings gelesen, deren Ablaufdaten weiterhin unverändert geprüft werden.
"""
import re
from urllib.parse import urljoin

from scrapling import Selector

import geo
from extraction import is_detail
from retail_region import AREA_KM, AREA_NAME, regional_details
from safe_http import FetchError

PUBLIC_LIST = "https://toom-baumarkt.dvinci-easy.com/de/jobs/iframe"


def toom(source, req, get, report):
    from employer_adapters import json_document

    final, html = get(PUBLIC_LIST, source)
    links = {}
    for href in Selector(html).css('a::attr(href)').getall():
        url = urljoin(final, href)
        match = re.search(r"/de/jobs/(\d+)/", url)
        if match and is_detail(url, source):
            links[match.group(1)] = url
    if not links:
        raise FetchError("unsupported", detail="toom-Originalstellenliste fehlt")
    lat, lng = geo.center(AREA_NAME)
    payload = {"search": {"term": req.q, "filters": {}, "location": {
        "lat": lat, "lng": lng, "range": AREA_KM}, "sort": "date"}}
    urls, seen = [], set()
    for page in range(1, getattr(req, "max_pages", source.max_pages) + 1):
        data = json_document(get, source.api + f"?type=jobs&page={page}", source, payload)
        rows = data.get("results") if isinstance(data, dict) else None
        meta = data.get("meta") if isinstance(data, dict) else None
        if (not isinstance(rows, list) or not isinstance(meta, dict)
                or not isinstance(meta.get("totalPages"), int) or meta["totalPages"] < 0
                or meta.get("page") != page):
            raise FetchError("unsupported", detail="Ungültige toom-Suchantwort")
        for row in rows:
            ident = str(row.get("externalId", "")) if isinstance(row, dict) else ""
            # Einzelne Lücken (Anzeige zwischen Liste und Suche neu oder weg) und Wiederholungen
            # überspringen, statt die ganze Quelle zu verwerfen.
            if ident not in links or ident in seen:
                report["filtered"] += 1
                continue
            seen.add(ident)
            urls.append(links[ident])
        if page >= meta["totalPages"]:
            break
        if not rows:
            raise FetchError("unsupported", detail="toom-Suche endet vorzeitig")
    else:
        report["status"] = "result_limit"
    report["matched"] = len(urls)
    yield from regional_details(urls, source, req, get, report)
