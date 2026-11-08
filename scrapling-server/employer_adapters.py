"""Explicit employer formats. All network access goes through crawler.allowed_get.

No arbitrary API discovery, browser execution, guessed companies or fabricated jobs.
API records are mapped to the same strict JobPosting validation as HTML records.
"""
import hashlib
import json
import re
from urllib.parse import parse_qs, quote, urlsplit

from scrapling import Selector

from extraction import canonical, extract, is_detail, norm, plain
from safe_http import FetchError
from bite_adapter import bite
from carsonal_adapter import carsonal


def json_document(get, raw, source, payload=None):
    options = {"accept_json": True}
    if payload is not None:
        options["json_body"] = payload
    _, text = get(raw, source, **options)
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise FetchError("unsupported") from None


def from_record(row, raw, source, query):
    """Reuse expiry, company, URL and relevance checks without trusting HTML."""
    if not isinstance(row, dict):
        return None
    data = {"@type": "JobPosting", **row}
    safe = json.dumps(data).replace("<", "\\u003c")
    return extract('<script type="application/ld+json">' + safe + "</script>", raw, source, query)


def ranked(rows, query, title_key="title"):
    terms = norm(query).split()
    return sorted(rows, key=lambda row: -sum(
        term in norm(str(row.get(title_key, ""))) for term in terms))


def detail_document(get, raw, source, report, *, as_json=False):
    try:
        return json_document(get, raw, source) if as_json else get(raw, source)
    except FetchError as error:
        if error.code != "gone":
            raise
        report["filtered"] += 1
        return None


def workday(source, req, get, report):
    links = []
    limit = getattr(req, "max_details", 10)
    # Ortsfilter der konfigurierten Suchadresse (?locations=<32 Hex>) gelten auch für die Abfrage.
    facets = {}
    wanted = [v for v in parse_qs(urlsplit(source.search).query).get("locations", [])
              if re.fullmatch(r"[a-f0-9]{32}", v)]
    if wanted:
        facets["locations"] = wanted
    for offset in range(0, 200, 20):
        data = json_document(get, source.api, source, {
            "appliedFacets": facets, "limit": 20, "offset": offset, "searchText": req.q})
        rows = data.get("jobPostings") if isinstance(data, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise FetchError("unsupported")
        for row in ranked(rows, req.q):
            path = row.get("externalPath", "")
            # Workday paths are relative to this exact employer's board.
            if not isinstance(path, str) or not path.startswith("/job/"):
                continue
            raw = source.search.split("?", 1)[0].rstrip("/") + path
            if is_detail(raw, source) and raw not in links:
                links.append(raw)
        if len(links) >= limit or len(rows) < 20:
            break
    for raw in links[:limit]:
        document = detail_document(get, raw, source, report)
        if document is None:
            continue
        final, html = document
        job = extract(html, final, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1


def myjobboard(source, req, get, report):
    data = json_document(get, source.api, source)
    rows = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise FetchError("unsupported")
    seen = set()
    for row in ranked(rows, req.q):
        ident = row.get("id", "")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{24}", ident) or ident in seen:
            continue
        seen.add(ident)
        if len(seen) > 10:
            break
        raw = source.search.rstrip("/") + "/" + ident
        detail = detail_document(get, source.api.rstrip("/") + "/" + ident, source, report, as_json=True)
        if detail is None:
            continue
        postings = detail.get("jobs") if isinstance(detail, dict) else None
        if not isinstance(postings, list) or len(postings) != 1 or not isinstance(postings[0], dict):
            report["filtered"] += 1
            continue
        actual = postings[0]
        if (actual.get("id") != ident or actual.get("tenant") != "stadtwerke-waiblingen"
                or actual.get("accessibilityLevel") != "Public"):
            report["filtered"] += 1
            continue
        job = from_record({
            "title": actual.get("title"), "hiringOrganization": actual.get("hiringOrganization"),
            "description": actual.get("description"), "datePosted": actual.get("publishedAt"),
            "validThrough": actual.get("publishUntil"),
            "jobLocation": {"address": actual.get("postalAddress")},
        }, raw, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1


def easyhr(source, req, get, report):
    _, owner_html = get(source.start(req.q, req.location), source)
    owner = Selector(owner_html)
    company = owner.css('meta[property="og:site_name"]::attr(content)').get() or ""
    board = "3e591c90-d9bf-4ea5-ae09-9395cd2e322d"
    # The board must still be linked by the official employer, not guessed.
    if (not re.fullmatch(source.company_pattern, company, re.I)
            or not any("board[]=" + board in frame for frame in owner.css("iframe::attr(src)").getall())):
        raise FetchError("unsupported")
    rows = json_document(get, source.api, source)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise FetchError("unsupported")
    seen = set()
    for row in ranked(rows, req.q):
        ident = row.get("id", "")
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f-]{36}", ident) or ident in seen:
            continue
        seen.add(ident)
        if len(seen) > 10:
            break
        detail = detail_document(get, "https://apibetax.easyhr.io/position?id=" + ident, source, report, as_json=True)
        if detail is None:
            continue
        if (not isinstance(detail, dict) or detail.get("id") != ident
                or detail.get("customer_id") != board or detail.get("online") is not True):
            report["filtered"] += 1
            continue
        raw = "https://jobboard.easyhr.io/jobad/" + ident
        job = from_record({
            "title": detail.get("title"), "hiringOrganization": {"name": company},
            "description": detail.get("editor"), "validThrough": detail.get("end_date_apply"),
            "datePosted": detail.get("inserted_at"),
            "jobLocation": {"address": {"addressLocality": detail.get("location")}},
        }, raw, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1


def hahn(source, req, get, report):
    rows = []
    # Exactly the two public categories linked by Hahn's own Vue component.
    # Deliberately exclude the third, unsolicited-applications category.
    for category in ("d6c56453-b738-4567-a303-778b130447d8", "3acce8b1-2d67-4367-a289-5ed203c2f9c8"):
        data = json_document(get, source.api.replace("{category}", category), source)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise FetchError("unsupported")
        rows.extend(data)
    seen = set()
    for row in ranked(rows, req.q, "VacancyName"):
        raw = row.get("VacancyUrl", "")
        if not isinstance(raw, str) or not is_detail(raw, source) or canonical(raw) in seen:
            continue
        seen.add(canonical(raw))
        if len(seen) > 10:
            break
        document = detail_document(get, raw, source, report)
        if document is None:
            continue
        final, html = document
        job = extract(html, final, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1


def sections(source, req, get, report):
    final, html = get(source.start(req.q, req.location), source)
    # A redirect to a different page is not evidence for a site-specific layout.
    if canonical(final) != canonical(source.start(req.q, req.location)):
        raise FetchError("unsupported")
    page = Selector(html)
    if source.adapter == "benz_sections":
        publisher = page.css('meta[name="DC.Publisher"]::attr(content)').get() or ""
        titles = page.css(".typo h2")
    else:
        publisher = plain(" ".join(page.css(".accordion").xpath(
            "following::text()[not(ancestor::script)]").getall()))
        titles = page.css(".accordion h4.trigger")
    match = re.search(source.company_pattern, publisher, re.I)
    if not match:
        raise FetchError("unsupported")
    company = match.group(0)
    # Document order also handles BENZ's nested richtext containers. A direct
    # sibling-only split would leak the next nested vacancy into the previous one.
    order = {element: index for index, element in enumerate(page._root.iter())}
    text_nodes = page._root.xpath("//text()[not(ancestor::script) and not(ancestor::style)]")
    kept_titles = set()
    headings = list(titles)
    for heading_index, node in enumerate(headings[:40]):
        title = " ".join(plain(node.get()).split())
        if (len(title) > 200 or not re.search(r"\([mwfdgn/ -]+\)|Sicherungspersonal", title, re.I)
                or re.search(r"initiativ|initiative bewerbung", title, re.I)
                or title in kept_titles):
            continue
        kept_titles.add(title)
        if source.adapter == "eisenmann_sections":
            content = node.xpath("following-sibling::*[1][contains(@class,'toggle_container')]").get() or ""
        else:
            lower = order[node._root]
            upper = order[headings[heading_index + 1]._root] if heading_index + 1 < len(headings) else len(order)
            content = "\n".join(str(text) for text in text_nodes
                                if lower < order.get(text.getparent(), -1) < upper)
        description = plain(content)
        if len(description) < 100:
            report["filtered"] += 1
            continue
        location_match = re.search(r"Standort:\s*([^<\n]+)", content, re.I)
        location = location_match.group(1).split("Ihr Aufgabengebiet")[0].split("Ihre Qualifikation")[0].strip()[:160] if location_match else ""
        if source.adapter == "eisenmann_sections":
            location_match = re.search(r"für (Süd- und Mitteldeutschland|Süddeutschland)|in (Baden-Württemberg[^<]+)", title)
            location = location_match.group(0) if location_match else ""
        job = from_record({
            "title": title, "hiringOrganization": {"name": company},
            "description": description, "jobLocation": {"address": {"addressLocality": location}},
        }, canonical(final), source, req.q)
        if not job:
            report["filtered"] += 1
            continue
        # Text-fragments navigate to the actual evidenced role on this page.
        # Never import the complete multi-role index as one vacancy.
        raw = canonical(final) + "#:~:text=" + quote(title, safe="")
        yield {**job, "id": "scrapling-" + hashlib.sha256(raw.encode()).hexdigest()[:24], "url": raw}
        if len(kept_titles) >= 10:
            break


def adapter_jobs(source, req, get, report):
    if source.adapter in {"judo_filter", "harro_next"}:
        from regional_additions import judo, harro
        yield from (judo if source.adapter == "judo_filter" else harro)(source, req, get, report)
    elif source.adapter == "carsonal":
        yield from carsonal(source, req, get, report)
    elif source.adapter == "sitemap":
        from sitemap_adapter import sitemap
        yield from sitemap(source, req, get, report)
    elif source.adapter == "personio":
        from personio_adapter import personio
        yield from personio(source, req, get, report)
    elif source.adapter == "rems_list":
        from rems_adapter import rems_list
        yield from rems_list(source, req, get, report)
    elif source.adapter == "dvinci":
        from dvinci_adapter import dvinci
        yield from dvinci(source, req, get, report)
    elif source.adapter == "murr":
        from murr_adapter import murr
        yield from murr(source, req, get, report)
    elif source.adapter == "bite":
        yield from bite(source, req, get, report)
    elif source.adapter == "workday":
        yield from workday(source, req, get, report)
    elif source.adapter == "myjobboard":
        yield from myjobboard(source, req, get, report)
    elif source.adapter in {"benz_sections", "eisenmann_sections"}:
        yield from sections(source, req, get, report)
    elif source.adapter == "easyhr":
        yield from easyhr(source, req, get, report)
    elif source.adapter == "hahn":
        yield from hahn(source, req, get, report)
    else:
        raise FetchError("unsupported")
