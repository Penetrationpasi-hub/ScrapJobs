"""REWE/PENNY: öffentliche HTML-Suche, fest 50 km um Waiblingen."""
from urllib.parse import urlencode, urljoin

from scrapling import Selector

import geo
from extraction import canonical, extract, is_detail
from safe_http import FetchError


def career_search(source, req, get, report):
    from employer_adapters import detail_document

    origin = geo.center("Waiblingen")
    params = {"location": "Waiblingen", "range": 50, "lat": origin[0],
              "lng": origin[1], "term": req.q}
    seen = set()
    details = 0
    max_details = getattr(req, "max_details", source.max_details)
    for index in range(1, getattr(req, "max_pages", source.max_pages) + 1):
        url = source.search + "?" + urlencode({**params, "index": index})
        final, html = get(url, source)
        page = Selector(html)
        if not page.css('[data-job-search-results="root"]'):
            raise FetchError("unsupported", detail=f"{source.label}-Ergebnisliste fehlt")
        for row in page.css('.job-search__item'):
            raw = row.css('a.job-search__item-content::attr(href)').get()
            raw = canonical(urljoin(final, raw)) if raw else None
            if not raw or not is_detail(raw, source) or raw in seen:
                continue
            seen.add(raw)
            places = " | ".join(row.css('.job-search__item-multilocation::text').getall())
            if geo.in_range(origin, places, 50) is False:
                report["filtered"] += 1
                continue
            if details >= max_details:
                report["status"] = "result_limit"
                return
            details += 1
            document = detail_document(get, raw, source, report)
            if document is None:
                continue
            job = extract(document[1], document[0], source, req.q)
            if job and geo.in_range(origin, job.get("location", ""), 50) is True:
                yield job
            else:
                report["filtered"] += 1
        report["detail"] = f"Waiblingen + 50 km: {index} Suchseiten, {details} Einzelanzeigen geprüft"
        if not page.css('a.job-search-button-next:not(.is--disabled)::attr(href)').get():
            return
    report["status"] = "result_limit"
