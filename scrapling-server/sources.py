"""Server-owned discovery templates. Never accept URLs or selectors from a caller."""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    hosts: tuple[str, ...]
    search: str
    detail: str
    next_selector: str = 'a[rel="next"]::attr(href)'
    title_selector: str = ""
    company_selector: str = ""
    location_selector: str = ""
    description_selector: str = ""
    available: bool = True
    reference: str = ""
    note: str = ""
    company_pattern: str = ""
    adapter: str = "html"
    api: str = ""
    company_capture: str = ""
    max_pages: int = 2
    max_details: int = 10
    # Result lists with a place per teaser: skip listed ads that are clearly outside the search radius.
    teaser: str = ""
    teaser_location: str = ""
    # Nur Katalog-Lauf: Orte, für die die Suche je einmal mit {location} abgefragt wird (globale Konzernportale).
    catalog_locations: tuple[str, ...] = ()

    def start(self, q: str, location: str) -> str:
        return self.search.replace("{q}", quote(q, safe="")).replace("{location}", quote(location, safe=""))


BOARDS = (
    Source("indeed", "Indeed", ("de.indeed.com", "www.indeed.com"),
           "https://de.indeed.com/jobs?q={q}&l={location}", r"/(?:viewjob|rc/clk)(?:\?|$)",
           'a[data-testid="pagination-page-next"]::attr(href)',
           'h1.jobsearch-JobInfoHeader-title::text', '[data-testid="inlineHeader-companyName"] a::text',
           '[data-testid="inlineHeader-companyLocation"]::text', '#jobDescriptionText'),
    Source("stepstone", "StepStone", ("www.stepstone.de", "stepstone.de"),
           "https://www.stepstone.de/jobs/{q}/in-{location}", r"/stellenangebote--.+--\d+(?:-inline)?\.html",
           'a[rel="next"]::attr(href)',
           'h1[data-at="header-job-title"]::text', '[data-at="header-company-name"]::text',
           '[data-at="header-job-location"]::text', '[data-at="job-ad-content"]'),
)
# Explicit, replaceable pilot templates, NOT a claim of verified access or complete coverage.
EMPLOYERS = (
    Source("festo", "Festo", ("jobs.festo.com",),
           "https://jobs.festo.com/search/?q={q}&locationsearch={location}", r"/job/[^?#]+",
           note="Bei bestätigten Nulltreffern werden die allgemeinen Empfehlungen nicht als Suchtreffer geprüft.",
           catalog_locations=("Esslingen", "Ostfildern")),
    Source("bosch", "Bosch", ("careers.smartrecruiters.com", "jobs.smartrecruiters.com"),
           "https://careers.smartrecruiters.com/BoschGroup/?search={q}", r"/BoschGroup/\d+[^?#]*",
           note="Bewusst nicht gelesen: robots.txt von jobs.bosch.com sperrt /en/ (Anzeigen und Liste) für alle allgemeinen Crawler (Stand 2026-11-08), und die öffentliche SmartRecruiters-API untersagt allgemeines Crawling. Kein API-Ersatz und keine Umgehung."),
)


# Boards with a robots.txt crawl delay of 10 s: each one runs alone in its own group.
ISOLATED_SOURCES = ("rems_murr_jobs", "bluum_bw", "zvw")  # zvw reads its ads from rems-murr-jobs.de
# Aggregators are only searched when approved explicitly, never via the "employers" group.
AGGREGATOR_SOURCES = ("jobsuche_bw",)


def registry() -> dict[str, Source]:
    employers = EMPLOYERS
    if raw := os.environ.get("SCRAPLING_EMPLOYERS"):
        rows = json.loads(raw)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 30:
            raise ValueError("One to thirty employer configurations required")
        employers = tuple(Source(**{**row, "hosts": tuple(row["hosts"])}) for row in rows)
    catalog = json.loads(Path(__file__).with_name("employers.json").read_text(encoding="utf-8"))
    additions = tuple(Source(**{**{k: v for k, v in row.items() if k != "entries"}, "hosts": tuple(row["hosts"]),
                         "catalog_locations": tuple(row.get("catalog_locations", ()))}) for row in catalog)
    all_sources = (*BOARDS, *employers, *additions)
    result = {source.key: source for source in all_sources}
    if len(result) != len(all_sources) or len(result) > 100 or not {"indeed", "stepstone"}.issubset(result):
        raise ValueError("Unique source identifiers required")
    for source in result.values():
        if not re.fullmatch(r"[a-z0-9_-]{1,24}", source.key):
            raise ValueError("Invalid source identifier")
        if not source.available:
            if source.search or source.hosts or source.detail:
                raise ValueError("Unavailable sources must not configure network requests")
            continue
        url = urlparse(source.search)
        if url.scheme != "https" or url.hostname not in source.hosts or url.username or url.password or url.port:
            raise ValueError("Discovery URL must be HTTPS on an exact allowed host")
        if not source.detail:
            raise ValueError("Detail-page matcher required")
        re.compile(source.detail)
        if not (1 <= source.max_pages <= 3 and 1 <= source.max_details <= 10):
            raise ValueError("Page and detail limits must stay within the global caps")
        if source.catalog_locations and (
                "{location}" not in source.search or len(source.catalog_locations) > 8
                or not all(isinstance(place, str) and re.fullmatch(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .-]{1,39}", place)
                           for place in source.catalog_locations)):
            raise ValueError("Catalog locations need a {location} template and plain place names")
        if bool(source.teaser) != bool(source.teaser_location):
            raise ValueError("Teaser and teaser location selectors belong together")
        if source.company_pattern:
            re.compile(source.company_pattern)
        if source.company_capture:
            re.compile(source.company_capture)
        if source.adapter not in {"html", "workday", "myjobboard", "easyhr", "hahn", "benz_sections", "eisenmann_sections", "judo_filter", "harro_next", "bite", "carsonal", "murr", "dvinci", "rems_list", "personio", "sitemap", "datafeed"}:
            raise ValueError("Unknown employer adapter")
        if source.api:
            api = urlparse(source.api)
            if (api.scheme != "https" or api.hostname not in source.hosts or api.username
                    or api.password or api.port or api.fragment):
                raise ValueError("API must use an exact configured HTTPS host")
            if source.adapter == "workday" and not re.fullmatch(
                    r"/wday/cxs/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+/jobs", api.path):
                raise ValueError("Workday POST must use the public jobs-search path")
        if source.adapter == "bite" and (source.key != "zfp_winnenden"
                or source.api != "https://jobs.b-ite.com/api/v1/postings/search"):
            raise ValueError("B-ite reader is bound to ZFP's public posting search")
        if source.adapter == "carsonal" and (source.key != "burger_schloz"
                or source.api != "https://api.carsonal.de/rest"
                or source.search != "https://jobs.burgerschloz.de/de/"):
            raise ValueError("Carsonal reader is bound to Burger Schloz's public career page")
        if source.adapter == "datafeed" and not (source.api and source.api.endswith("/jobs.feed.json")):
            raise ValueError("Datafeed reader needs the portal's /jobs.feed.json")
        if source.adapter == "sitemap" and not (
                source.api and re.fullmatch(r"https://[a-z0-9.-]+/[A-Za-z0-9_./-]*sitemap[A-Za-z0-9_.-]*", source.api)):
            raise ValueError("Sitemap reader needs a plain sitemap URL on a configured host")
        if source.adapter == "personio" and (len(source.hosts) != 1 or not source.hosts[0].endswith(".jobs.personio.de")
                or source.api != f"https://{source.hosts[0]}/xml"):
            raise ValueError("Personio reader is bound to the tenant's public /xml feed")
        if source.adapter == "rems_list" and (source.key != "rems"
                or source.search != "https://recruitment.rems.de/stellenangebote"):
            raise ValueError("REMS reader is bound to REMS's public job list")
        if source.adapter == "murr" and (source.key != "murrelektronik"
                or source.search != "https://www.murrelektronik.com/de/landingpages/karriere/stellenangebote/"):
            raise ValueError("Murrelektronik reader is bound to its public job list")
        if source.adapter in {"workday", "myjobboard", "easyhr", "hahn", "bite", "personio"} and not source.api:
            raise ValueError("Employer API endpoint required")
    return result


def approved_sources(sources=None):
    sources = sources if sources is not None else registry()
    approved = {part.strip() for part in os.environ.get("SCRAPLING_APPROVED_SOURCES", "").split(",")}
    if "employers" in approved:
        approved.update(key for key, source in sources.items() if key not in {"indeed", "stepstone", *ISOLATED_SOURCES, *AGGREGATOR_SOURCES} and source.available)
    return {key for key in approved if key in sources and sources[key].available}
