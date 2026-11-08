"""Burger Schloz's public Carsonal documents; no authorized/apply endpoints."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from scrapling import Selector

from extraction import extract, norm, plain
from safe_http import FetchError


OWNER = "https://jobs.burgerschloz.de"
ROOT = "https://api.carsonal.de/rest"
TENANT = ROOT + "/public/career_page-jobs.burgerschloz.de"
ENV = OWNER + "/assets/env.js"
EMPLOYER = "Burger Schloz Automobile GmbH & Co. KG"
PAGE_ID = "12"
APP_ID = "5EP27P93BE"
SEARCH_HOST = "5ep27p93be-dsn.algolia.net"
INDEX = "career_page_publications"
SEARCH_PATH = "/1/indexes/" + INDEX
REFERENCE = r"VO[0-9]{4}-[0-9]{6}"


def missing_robots_scope(raw, source, options):
    """A source-specific direct-404 exception, NOT permission to ignore robots."""
    if (source.key != "burger_schloz" or source.adapter != "carsonal"
            or not options.get("accept_json") or options.get("json_body") is not None):
        return False
    url = urlsplit(raw)
    if (url.scheme != "https" or url.username or url.password or url.port
            or url.fragment or "\\" in raw or any(ord(c) < 32 for c in raw)):
        return False
    if url.hostname == "api.carsonal.de" and not url.query:
        if raw == ROOT:
            return not options.get("json_api")
        return bool(options.get("json_api") and
                    (raw == TENANT or re.fullmatch(re.escape(TENANT) + "/publication-" + REFERENCE, raw)))
    if url.hostname == SEARCH_HOST and url.path == SEARCH_PATH and not options.get("json_api"):
        params = parse_qs(url.query, keep_blank_values=True)
        keys = {"query", "facetFilters", "filters", "hitsPerPage", "page",
                "x-algolia-application-id", "x-algolia-api-key"}
        if set(params) != keys or any(len(v) != 1 for v in params.values()):
            return False
        return bool(params["x-algolia-application-id"] == [APP_ID]
                    and params["facetFilters"] == ['[["career_page_id:12"]]']
                    and params["hitsPerPage"] == ["20"] and params["page"] == ["0"]
                    and len(params["query"][0]) <= 160
                    and re.fullmatch(r"[A-Za-z0-9+/=]{16,512}", params["x-algolia-api-key"][0])
                    and re.fullmatch(r"start_date <= ([0-9]{10}) AND \(end_date = 0 OR end_date >= \1\)",
                                     params["filters"][0]))
    return False


def _json(get, raw, source, **options):
    final, text = get(raw, source, accept_json=True, **options)
    if final != raw:
        raise FetchError("unsupported")
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise FetchError("unsupported") from None
    if not isinstance(data, dict):
        raise FetchError("unsupported")
    return data


def _tenant(document):
    data = document.get("data")
    if not isinstance(data, dict) or data.get("type") != "career_pages" or str(data.get("id")) != PAGE_ID:
        raise FetchError("unsupported")
    attributes = data.get("attributes")
    if (not isinstance(attributes, dict) or attributes.get("custom_domain") != "jobs.burgerschloz.de"
            or attributes.get("custom_domain_status") != "READY"
            or plain(attributes.get("contact_company_name")) != EMPLOYER):
        raise FetchError("unsupported")
    return data


def public_context(source, get):
    if source.key != "burger_schloz" or source.api != ROOT:
        raise FetchError("unsupported")
    final, html = get(source.search, source)
    if final != source.search:
        raise FetchError("unsupported")
    scripts = Selector(html).css("script[src]::attr(src)").getall()
    if not any(src in {"assets/env.js", "/assets/env.js", ENV} for src in scripts):
        raise FetchError("unsupported")
    final, script = get(ENV, source, accept_javascript=True)
    if final != ENV or not all(re.search(r"\b" + field + r"""\s*:\s*['"]""" + re.escape(value) + r"""['"]""", script)
                              for field, value in [("BACKEND_DOMAIN", "api.carsonal.de"),
                                                   ("BACKEND_API_PATH", "/rest"),
                                                   ("BACKEND_PROTOCOL", "https://")]):
        raise FetchError("unsupported")
    root = _json(get, ROOT, source)
    links = root.get("links", {})
    expected = {"public_career_page": ROOT + "/public/career_page-{domain}",
                "public_career_page_publication": ROOT + "/public/career_page-{domain}/publication-{reference_code}"}
    if not isinstance(links, dict) or any(not isinstance(links.get(key), dict)
            or links[key].get("href") != value for key, value in expected.items()):
        raise FetchError("unsupported")
    _tenant(_json(get, TENANT, source, json_api=True))
    return root


def _active(start, end):
    now = datetime.now(timezone.utc).timestamp()
    if (isinstance(start, bool) or not isinstance(start, (int, float))
            or isinstance(end, bool) or not isinstance(end, (int, float))):
        return False
    return 0 < start <= now and (end == 0 or end > now)


def verified_publication(data, hit, source, query):
    """Require index, public document and included employer to agree."""
    reference = hit.get("reference_code")
    slug = hit.get("seo_publication_identifier")
    ident = hit.get("objectID")
    if (not isinstance(reference, str) or not re.fullmatch(REFERENCE, reference)
            or not isinstance(ident, str) or not re.fullmatch(r"[0-9]{1,12}", ident)
            or str(hit.get("career_page_id")) != PAGE_ID
            or not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]+-" + re.escape(reference), slug)
            or not _active(hit.get("start_date"), hit.get("end_date"))):
        return None
    row = data.get("data")
    if not isinstance(row, dict) or row.get("type") != "publications" or row.get("id") != ident:
        return None
    attrs = row.get("attributes")
    relations = row.get("relationships", {})
    if not isinstance(attrs, dict) or not isinstance(relations, dict):
        return None
    relation = relations.get("career_page", {})
    if (not isinstance(relation, dict) or relation.get("data") != {"type": "career_pages", "id": PAGE_ID}
            or attrs.get("reference_code") != reference or attrs.get("seo_publication_identifier") != slug
            or not isinstance(attrs.get("settings"), dict) or attrs["settings"].get("channel") != "CAREER_PAGE"):
        return None
    included = data.get("included", [])
    if not isinstance(included, list):
        return None
    tenants = [r for r in included if isinstance(r, dict) and r.get("type") == "career_pages"]
    if len(tenants) != 1:
        return None
    try:
        _tenant({"data": tenants[0]})
    except FetchError:
        return None
    job, place = attrs.get("job_posting"), attrs.get("workplace")
    if (not isinstance(job, dict) or not isinstance(place, dict) or plain(place.get("company_name")) != EMPLOYER
            or plain(job.get("title")) != plain(hit.get("job_posting_title"))
            or not plain(job.get("title"))):
        return None
    try:
        start = datetime.fromisoformat(attrs["start_date"].replace("Z", "+00:00"))
        if start.tzinfo is None or start > datetime.now(timezone.utc):
            return None
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    pieces = []
    for field in ("introduction", "tasks", "profile", "offer", "conclusion"):
        section = job.get(field)
        if isinstance(section, dict):
            pieces.append(plain(section.get("headline")) + " " + plain(section.get("content")))
    description = " ".join(p for p in pieces if p.strip())
    if not description.strip():
        return None
    raw = OWNER + "/de/jobs/" + slug
    posting = {"@type": "JobPosting", "title": job["title"], "url": raw,
               "hiringOrganization": {"name": plain(place["company_name"])},
               "description": description, "datePosted": start.date().isoformat(),
               "jobLocation": {"address": {"addressLocality": plain(place.get("city")),
                                            "postalCode": plain(place.get("zip")),
                                            "addressCountry": plain(place.get("country"))}}}
    if hit["end_date"]:
        try:
            posting["validThrough"] = datetime.fromtimestamp(hit["end_date"], timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    # The shared validator rejects initiative/expired/search-page/nonmatching jobs.
    safe = json.dumps(posting).replace("<", "\\u003c")
    return extract('<script type="application/ld+json">' + safe + "</script>", raw, source, query)


def carsonal(source, req, get, report):
    root = public_context(source, get)
    meta = root.get("meta")
    config = meta.get("algolia") if isinstance(meta, dict) else None
    if (not isinstance(config, dict) or config.get("app_id") != APP_ID
            or not isinstance(config.get("indices"), dict) or config["indices"].get(INDEX) != INDEX
            or not isinstance(config.get("api_key"), str)
            or not re.fullmatch(r"[A-Za-z0-9+/=]{16,512}", config["api_key"])):
        raise FetchError("unsupported")
    now = int(datetime.now(timezone.utc).timestamp())
    params = {"query": req.q[:160], "facetFilters": '[["career_page_id:12"]]',
              "filters": f"start_date <= {now} AND (end_date = 0 OR end_date >= {now})",
              "hitsPerPage": "20", "page": "0", "x-algolia-application-id": APP_ID,
              "x-algolia-api-key": config["api_key"]}
    # Public search-only identity is obtained per run, never stored or returned.
    result = _json(get, "https://" + SEARCH_HOST + SEARCH_PATH + "?" + urlencode(params), source)
    hits = result.get("hits")
    if not isinstance(hits, list) or len(hits) > 20 or any(not isinstance(row, dict) for row in hits):
        raise FetchError("unsupported")
    terms = norm(req.q).split()
    hits.sort(key=lambda row: -sum(term in norm(str(row.get("job_posting_title", ""))) for term in terms))
    seen, fetched = set(), 0
    for hit in hits:
        reference = hit.get("reference_code")
        if (not isinstance(reference, str) or not re.fullmatch(REFERENCE, reference)
                or str(hit.get("career_page_id")) != PAGE_ID
                or not _active(hit.get("start_date"), hit.get("end_date"))):
            report["filtered"] += 1
            continue
        if reference in seen:
            continue
        seen.add(reference)
        if fetched >= 10:
            break
        fetched += 1
        try:
            document = _json(get, TENANT + "/publication-" + reference, source, json_api=True)
        except FetchError as error:
            if error.code != "gone":
                raise
            report["filtered"] += 1
            continue
        job = verified_publication(document, hit, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
