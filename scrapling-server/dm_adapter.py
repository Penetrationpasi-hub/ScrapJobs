"""dm: offizielle Jobs-Sitemap, Vorfilter über PLZ im Slug, bestätigter Detailort."""
import re
from urllib.parse import urlsplit

import geo
from extraction import is_detail
from retail_region import regional_details
from sitemap_adapter import locations


def dm(source, req, get, report):
    _, text = get(source.api, source, accept_xml=True, max_body=6 * 1024 * 1024)
    urls = locations(text)
    origin = geo.center("Waiblingen")
    selected = []
    for url in urls:
        if not is_detail(url, source):
            continue
        postcode = re.search(r"-in-(\d{5})(?:-|/)", urlsplit(url).path)
        if postcode and geo.in_range(origin, postcode.group(1), 50) is False:
            continue
        selected.append(url)
    report["urls"], report["matched"] = len(urls), len(selected)
    yield from regional_details(selected, source, req, get, report)
