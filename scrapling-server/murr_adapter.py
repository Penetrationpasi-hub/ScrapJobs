"""Murrelektronik's public TYPO3 job pages (no JobPosting data, DOM evidence only)."""
import json
import re
from urllib.parse import urlsplit

from scrapling import Selector

from employer_adapters import from_record
from extraction import canonical, discovery, plain
from safe_http import FetchError

EMPLOYER = "Murrelektronik GmbH"
HOST = "www.murrelektronik.com"
LIST_PATH = "/de/landingpages/karriere/stellenangebote/"
EXPIRED = re.compile(r"(job|stelle|anzeige).{0,45}(abgelaufen|nicht mehr (verfügbar|online)|bereits besetzt)", re.I)
DETAIL = r"^/de/landingpages/karriere/stellenangebote/detail/job/[a-z0-9-]+/?$"


def missing_robots_scope(raw, source, options):
    """Exact GET routes of the user-approved exception; not a general robots bypass.

    www.murrelektronik.com/robots.txt answers 301 to an HTML page, so no robots
    rules can be read. Only the public list and /detail/job/ pages are covered.
    """
    if source.key != "murrelektronik" or source.adapter != "murr" or options:
        return False
    url = urlsplit(raw)
    if (url.scheme != "https" or url.hostname != HOST or url.username or url.password
            or url.port or url.query or url.fragment or "\\" in raw):
        return False
    return url.path == LIST_PATH or bool(re.fullmatch(DETAIL, url.path))


def _organization(page):
    """The employer must be proven by the page's own Corporation structured data."""
    for script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(script)
        except (ValueError, TypeError):
            continue
        for row in data if isinstance(data, list) else [data]:
            if isinstance(row, dict) and row.get("@type") == "Corporation" and plain(row.get("name")) == EMPLOYER:
                return EMPLOYER
    return ""


def murr(source, req, get, report):
    final, html = get(source.search, source)
    if canonical(final) != canonical(source.search):
        raise FetchError("unsupported")
    links, _ = discovery(html, final, source, req.q)
    if not links:
        report["status"] = "unsupported"
    for url in links[:10]:
        try:
            target, page_html = get(url, source)
        except FetchError as error:
            if error.code != "gone":
                raise
            report["filtered"] += 1
            continue
        if canonical(target) != canonical(url):
            report["filtered"] += 1
            continue
        page = Selector(page_html)
        headings = page.css("h1.leadHeadline")
        company = _organization(page)
        body = page.css(".contentElementContainer")
        description = " ".join(plain(" ".join(body.css("::text").getall())).split()) if body else ""
        if (len(headings) != 1 or not company or len(description) < 100
                or EXPIRED.search(description)):
            report["filtered"] += 1
            continue
        meta = " ".join(page.css('meta[name="description"]::attr(content)').getall())
        place = re.search(r"Standort in ([A-ZÄÖÜ][\wäöüß-]+)", meta)
        row = {"title": plain(headings[0].get()), "hiringOrganization": {"name": company},
               "description": description, "url": canonical(target)}
        if place:
            row["jobLocation"] = {"address": {"addressLocality": place[1]}}
        job = from_record(row, canonical(target), source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
