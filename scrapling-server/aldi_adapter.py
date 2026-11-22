"""ALDI SÜD: öffentliche Stellenkarte mit Koordinaten, Details bei SuccessFactors."""
import math
from urllib.parse import parse_qs, urljoin, urlsplit

from scrapling import Selector

import geo
from retail_region import AREA_KM, AREA_NAME, regional_details
from safe_http import FetchError


def aldi(source, req, get, report):
    from employer_adapters import json_document

    final, html = get(source.search, source)
    endpoint = Selector(html).css('custom-job-search::attr(jobmapapi)').get()
    if not endpoint:
        raise FetchError("unsupported", detail="ALDI-Stellenkarte fehlt")
    endpoint = urljoin(final, endpoint)
    parsed = urlsplit(endpoint)
    params = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.netloc != "karriere.aldi-sued.de" or parsed.path != "/"
            or params.get("tx_uialdisuedjobs_ads[action]") != ["getJobmapItems"]):
        raise FetchError("unsupported", detail="Unbekannter ALDI-Kartenendpunkt")
    data = json_document(get, endpoint, source)
    rows = data.get("result") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise FetchError("unsupported", detail="ALDI-Stellenkarte ohne result-Liste")
    origin = geo.center(AREA_NAME)
    urls = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            raise FetchError("unsupported", detail="Ungültiger ALDI-Karteneintrag")
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
            if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            # Ohne belastbare Koordinaten entscheidet die verifizierte Detailadresse.
            urls.append(row["url"])
            continue
        if geo.km(origin, (lat, lng)) <= AREA_KM:
            urls.append(row["url"])
    report["urls"], report["matched"] = len(rows), len(urls)
    yield from regional_details(urls, source, req, get, report)
