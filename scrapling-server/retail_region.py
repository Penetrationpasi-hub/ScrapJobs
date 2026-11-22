"""Gemeinsame Detailprüfung für das feste Suchgebiet Waiblingen + 50 km."""
import geo
from extraction import canonical, extract, is_detail

# Festes Suchgebiet aller regionalen Händler-Adapter (ALDI, dm, toom, REWE, PENNY); auch Grundlage von batch.AREA.
AREA_NAME = "Waiblingen"
AREA_KM = 50


def regional_details(urls, source, req, get, report):
    from employer_adapters import detail_document

    origin = geo.center(AREA_NAME)
    seen = set()
    count = 0
    for url in urls:
        if not isinstance(url, str) or not is_detail(url, source):
            report["filtered"] += 1
            continue
        url = canonical(url)
        if url in seen:
            continue
        seen.add(url)
        if count >= getattr(req, "max_details", source.max_details):
            report["status"] = "result_limit"
            return
        count += 1
        document = detail_document(get, url, source, report)
        if document is None:
            continue
        job = extract(document[1], document[0], source, req.q)
        if job and geo.in_range(origin, job.get("location", ""), AREA_KM) is True:
            yield job
        else:
            report["filtered"] += 1
    report["detail"] = f"{AREA_NAME} + {AREA_KM} km: {count} Einzelanzeigen geprüft"
