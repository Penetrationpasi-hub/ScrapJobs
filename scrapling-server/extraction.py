"""Scrapling selectors + verified JobPosting fields, never model-generated metadata."""
import hashlib
import html as htmllib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from scrapling import Selector


def plain(value):
    if not isinstance(value, str):
        return ""
    return " ".join(Selector("<div>" + value[:20000] + "</div>").xpath("//text()[not(ancestor::script) and not(ancestor::style)]").getall()).strip()[:4000]


def canonical(raw):
    u = urlsplit(raw)
    return urlunsplit((u.scheme, u.netloc, u.path.rstrip("/") or "/",
                      urlencode(sorted((k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith("utm_") and k.lower() not in ("gclid", "fbclid"))), ""))


def is_detail(raw, source):
    u = urlsplit(raw)
    return (u.scheme == "https" and u.hostname in source.hosts and not u.username and not u.password
            and bool(re.search(source.detail, u.path + ("?" + u.query if u.query else "")))
            and not re.search(r"/(?:jobs|careers|karriere|stellenangebote|search)/?$", u.path, re.I))


def discovery(html, base, source, q="", near=None):
    """Detail links of a result page. `near(place_text)` may veto a teaser whose listed place is out of range."""
    page = Selector(html)
    links = []
    scores = {}
    terms = norm(q).split()
    skip = set()
    if near and source.teaser:
        for teaser in page.css(source.teaser):
            place = " ".join(plain(part) for part in teaser.css(source.teaser_location).getall())
            if near(place) is False:
                skip.update(canonical(urljoin(base, value)) for value in teaser.css("a::attr(href)").getall())
    for anchor in page.css("a[href]"):
        value = anchor.attrib.get("href", "")
        raw = urljoin(base, value)
        if is_detail(raw, source) and canonical(raw) not in links and canonical(raw) not in skip:
            links.append(canonical(raw))
            label = norm(plain(anchor.get()) + " " + raw)
            scores[canonical(raw)] = sum(term in label for term in terms)
    links.sort(key=lambda link: -scores[link])
    next_url = page.css(source.next_selector).get() if source.next_selector else None
    return links, urljoin(base, next_url) if next_url else None


def entries(value):
    if isinstance(value, list):
        for row in value:
            yield from entries(row)
    elif isinstance(value, dict):
        typ = value.get("@type")
        if typ == "JobPosting" or isinstance(typ, list) and "JobPosting" in typ:
            yield value
        if "@graph" in value:
            yield from entries(value["@graph"])


def norm(value):
    return unicodedata.normalize("NFKD", value).casefold()


def extract(html, raw, source, q="", now=None):
    if not is_detail(raw, source):
        return None
    page = Selector(html)
    text = plain(html)
    if re.search(r"(job|stelle|anzeige).{0,45}(abgelaufen|nicht mehr (verfügbar|online)|bereits besetzt)|no longer accepting|job has expired", text, re.I):
        return None
    postings = []
    for script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            postings.extend(entries(json.loads(script)))
        except (ValueError, TypeError):
            continue
    # A page advertising multiple roles is not evidence of a single vacancy.
    if len(postings) > 1:
        return None
    if postings:
        row = postings[0]
        title = plain(row.get("title"))
        organization = row.get("hiringOrganization")
        company = plain(organization.get("name")) if isinstance(organization, dict) else ""
        if row.get("url") and canonical(urljoin(raw, str(row["url"]))) != canonical(raw):
            return None
        expiry = row.get("validThrough")
        if expiry:
            try:
                parsed = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed < (now or datetime.now(timezone.utc)):
                    return None
            except ValueError:
                return None
        locations = row.get("jobLocation") or []
        if isinstance(locations, dict):
            locations = [locations]
        places = []
        for loc in locations if isinstance(locations, list) else []:
            addr = loc.get("address", {}) if isinstance(loc, dict) else {}
            if isinstance(addr, dict):
                country = addr.get("addressCountry", "")
                if isinstance(country, dict):
                    country = country.get("name", "")
                parts = [plain(addr.get(k)) for k in ("postalCode", "addressLocality", "addressRegion")]
                places.append(" ".join(p for p in [*parts, plain(country)] if p))
        location = " / ".join(places)
        raw_description = row.get("description")
        # Some platforms (Jobiqo) ship the description entity-escaped inside the JSON.
        if isinstance(raw_description, str) and "<" not in raw_description and re.search(r"&lt;/?[a-z]", raw_description):
            raw_description = htmllib.unescape(raw_description)
        description = plain(raw_description) or None
        posted = row.get("datePosted", "")
        posted = posted[:10] if isinstance(posted, str) and re.match(r"^\d{4}-\d\d-\d\d", posted) else ""
    elif source.title_selector and source.company_selector:
        def field(selector):
            return plain(" ".join(page.css(selector).getall())) if selector else ""
        title, company = field(source.title_selector), field(source.company_selector)
        location, description, posted = field(source.location_selector), field(source.description_selector) or None, ""
        if source.company_capture:
            match = re.search(source.company_capture, company, re.I)
            company = match.group(0) if match else ""
    else:
        return None
    if (not title or not company or re.search(r"initiativbewerbung|unsolicited application|talent.?pool|general application", title, re.I)
            or re.search(r"verschiedene|mehrere|diverse|unbekannt|nicht angegeben", company, re.I)
            or re.search(r"\d+\s+(?:offene\s+)?(?:jobs|stellen|treffer)|suchergebnisse", title, re.I)):
        return None
    if source.company_pattern and not re.search(source.company_pattern, company, re.I):
        return None
    # Search pages can ignore search terms; keep query relevance grounded in extracted text.
    if q and not any(word in norm(title + " " + (description or "")) for word in norm(q).split()):
        return None
    url = canonical(raw)
    if source.key in {"rems_murr_jobs", "zvw"} and description and len(description) > 480:
        description = description[:480].rsplit(" ", 1)[0] + " …"
    return {"id": "scrapling-" + hashlib.sha256(url.encode()).hexdigest()[:24],
            "title": title[:200], "company": company[:120], "location": location[:200], "url": url,
            "source": source.label + " · Scrapling", "salary": None, "posted": posted,
            "description": description}
