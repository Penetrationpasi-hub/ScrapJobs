"""Observed JUDO and Harro Höfliger formats; all requests use the guarded crawler."""
import json
import re
from urllib.parse import urlencode

from scrapling import Selector
from extraction import canonical, discovery, extract, is_detail, norm, plain
from safe_http import FetchError


def text(page, selector):
    return " ".join(plain(" ".join(page.css(selector).getall())).split())


def judo(source, req, get, report):
    final, html = get(source.search, source)
    if canonical(final) != canonical(source.search):
        raise FetchError("unsupported")
    page = Selector(html)
    forms = page.css("form#filter-all")
    if len(forms) != 1 or forms[0].attrib.get("action") != source.api:
        raise FetchError("unsupported")
    nonce = forms[0].css('input[name="custom_stellenanzeigen_nonce"]::attr(value)').get()
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{10}", nonce):
        raise FetchError("unsupported")
    # Official public read-only action; never send applications or arbitrary POSTs.
    url = source.api + "?" + urlencode({
        "action": "jobfilter", "custom_stellenanzeigen_nonce": nonce,
        "job_level": "", "land_regionen": "", "tatigkeitsbereich": ""})
    _, raw = get(url, source, accept_json=True)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise FetchError("unsupported") from None
    if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), str):
        raise FetchError("unsupported")
    links, _ = discovery(data["data"], final, source, req.q)
    if not links:
        report["status"] = "unsupported"
    for url in links[:10]:
        target, html = get(url, source)
        if canonical(target) != canonical(url):
            report["filtered"] += 1
            continue
        page = Selector(html)
        title = text(page, ".container.wrapper h3.wp-block-heading")
        description = text(page, ".container.wrapper > .row > .col-md-12")
        company = re.search(r"\bJUDO Wasseraufbereitung GmbH\b", description)
        location = ""
        for paragraph in page.css(".container.wrapper p"):
            match = re.search(r"(?:am Standort|an unserem Standort in)\s+(.+?)\s+(?:einen|eine|ein)\b",
                              plain(paragraph.get()), re.I)
            if match:
                location = match[1]
                break
        if not title or not company or len(description) < 100:
            report["filtered"] += 1
            continue
        row = {"@type": "JobPosting", "title": title, "description": description,
               "hiringOrganization": {"name": company[0]},
               "jobLocation": {"address": {"addressLocality": location}}}
        payload = json.dumps(row).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + payload + "</script>", target, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1


def harro_records(html):
    """Decode JSON strings in Next's server-rendered data; never execute JS."""
    chunks = []
    for script in Selector(html).css("script::text").getall():
        script = script.strip().rstrip(";")
        prefix = "self.__next_f.push("
        if not script.startswith(prefix) or not script.endswith(")"):
            continue
        try:
            row = json.loads(script[len(prefix):-1])
        except ValueError:
            continue
        if isinstance(row, list) and len(row) == 2 and row[0] == 1 and isinstance(row[1], str):
            chunks.append(row[1])
    flight = "".join(chunks)
    lists = []
    for match in re.finditer(r'"jobs"\s*:\s*(\[)', flight):
        try:
            rows, _ = json.JSONDecoder().raw_decode(flight[match.start(1):])
        except ValueError:
            raise FetchError("unsupported") from None
        if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
            raise FetchError("unsupported")
        lists.append(rows)
    if len(lists) != 1:
        raise FetchError("unsupported")
    return lists[0]


def harro(source, req, get, report):
    final, html = get(source.search, source)
    if canonical(final) != canonical(source.search):
        raise FetchError("unsupported")
    rows = harro_records(html)
    if not rows:
        report["status"] = "no_matches"
        return
    terms = norm(req.q).split()
    rows.sort(key=lambda row: -sum(term in norm(str(row.get("title", ""))) for term in terms))
    seen = set()
    for row in rows:
        url, title = row.get("link"), row.get("title")
        if (row.get("locale") != "de" or not re.fullmatch(r"\d+-de_DE", str(row.get("jobId", "")))
                or not isinstance(title, str) or not title.strip()
                or not isinstance(url, str) or not is_detail(url, source)):
            report["filtered"] += 1
            continue
        if re.search(r"initiativbewerbung|talent.?pool", title, re.I) or url in seen:
            continue
        if len(seen) >= 10:
            break
        seen.add(url)
        target, content = get(url, source)
        job = extract(content, target, source, req.q) if canonical(target) == canonical(url) else None
        if job and norm(job["title"]) == norm(title):
            yield job
        else:
            report["filtered"] += 1
