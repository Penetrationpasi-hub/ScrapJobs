"""Trabajo.org (de.trabajo.org): server-rendered job search with radius filtering.

Trabajo exposes a normal HTML result page whose URL contains the keyword and,
when present, the place (``/stellenangebote-<keyword>/<place>``). Each result
contains a real ``stellenangebot-<tenant>-<hash>`` link and a listed location.
That is a better discovery source for a radius search than Trabajo's very large
anonymous job sitemap: the sitemap URLs contain no title or place, so selecting
nearby jobs from it would require downloading and probing an arbitrary number of
 detail pages.

The result page is only used to discover and rank links. Detail pages are still
passed through the common verified JobPosting extraction. The teaser location
avoids detail requests outside the requested radius; the location on the
verified detail page is checked once more before yielding the job.
"""
import re
import unicodedata
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from scrapling import Selector

import geo
from employer_adapters import detail_document
from extraction import discovery, extract


BASE = "https://de.trabajo.org"
SEARCH_PREFIX = "/stellenangebote"


def slug(value):
    """Trabajo's path segments are lower-case words joined by hyphens.

    Everything that is not a letter or digit becomes a hyphen, so a caller can
    never inject a host, query, or extra path segment through the keyword or the
    place. German umlauts are transliterated the way the portal spells them.
    """
    folded = unicodedata.normalize("NFKC", (value or "").strip().casefold())
    for umlaut, plain_text in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        folded = folded.replace(umlaut, plain_text)
    ascii_only = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", ascii_only)).strip("-")[:80]


def search_url(q="", location=""):
    """Build Trabajo's public search URL for the supplied search parameters.

    The keyword belongs to the path segment itself
    (``/stellenangebote-<keyword>``), and with a keyword the place is appended
    as its own segment (``/stellenangebote-<keyword>/<place>``). Without a
    keyword the portal's place index is ``/stellenangebote/<Place>`` (the
    URL-encoded place name): that page is already limited to the
    town, so the catalog can read it instead of the nationwide list.
    """
    keyword = slug(q)
    place = location.strip()
    if keyword:
        path = f"{SEARCH_PREFIX}-{keyword}"
        if folded := slug(place):
            path = f"{path}/{folded}"
        return BASE + path
    if place:
        return f"{BASE}{SEARCH_PREFIX}/{quote(place, safe='')}"
    return BASE + SEARCH_PREFIX


def _page_number(raw):
    try:
        return max(1, int(parse_qs(urlsplit(raw).query).get("page", ["1"])[0]))
    except (TypeError, ValueError):
        return 1


def _next_page(html, final, source):
    """Choose the next numbered result page, not the current/previous link."""
    current = _page_number(final)
    candidates = []
    page = Selector(html)
    for anchor in page.css('nav[aria-label="Page navigation"] a[href]'):
        raw = urljoin(final, anchor.attrib.get("href", ""))
        url = urlsplit(raw)
        if (url.scheme != "https" or url.hostname not in source.hosts or url.username or url.password
                or url.port not in (None, 443) or not url.path.startswith(SEARCH_PREFIX)):
            continue
        number = _page_number(raw)
        if number > current:
            candidates.append((number, raw))
    return min(candidates)[1] if candidates else None


def _in_radius(job, origin, radius):
    """Return False only for a known, verified location outside the radius."""
    if origin is None:
        return True
    distance = geo.distance_km(origin, job.get("location", ""))
    return distance is None or distance <= radius


def trabajo(source, req, get, report):
    """Read Trabajo result pages and verify only relevant detail pages."""
    location = getattr(req, "location", "")
    origin = geo.center(location) if location else None
    radius = getattr(req, "radius_km", 25)
    near = (lambda place: geo.in_range(origin, place, radius)) if origin else None
    # Internal catalog requests supply larger budgets; the public Search model
    # does not accept these fields and retains the source's live defaults.
    limit = getattr(req, "max_details", source.max_details)
    pages_limit = getattr(req, "max_pages", source.max_pages)
    current = search_url(req.q, location)
    visited = set()
    details = []
    listed = 0
    pages = 0

    while current and current not in visited and pages < pages_limit:
        visited.add(current)
        final, html = get(current, source)
        pages += 1
        # Without `near` the same call returns every ad of the page: the difference
        # is what the teaser radius filter kept out of the detail requests.
        listed += len(discovery(html, final, source, req.q)[0])
        for link in discovery(html, final, source, req.q, near)[0]:
            if link not in details:
                details.append(link)
        if len(details) >= limit:
            break
        current = _next_page(html, final, source)

    report["urls"] = listed
    report["matched"] = len(details)
    report["detail"] = f"{listed} Anzeigen auf {pages} Suchseite(n), {len(details)} im Umkreis"

    for raw in details[:limit]:
        document = detail_document(get, raw, source, report)
        if document is None:
            continue
        final, html = document
        why = []
        job = extract(html, final, source, req.q, why=why)
        if not job:
            report["filtered"] += 1
            if why and "sample" not in report:
                report["sample"] = raw + " " + "; ".join(why)
            continue
        if not _in_radius(job, origin, radius):
            report["filtered"] += 1
            continue
        yield job
