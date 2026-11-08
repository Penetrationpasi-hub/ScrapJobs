"""ZFP's officially embedded B-ite reader; no JavaScript execution or apply calls."""
import json
import re
from datetime import datetime, timezone

from scrapling import Selector

from extraction import entries, extract, norm, plain
from safe_http import FetchError


LISTING = "https://karriere.zfp-winnenden.de/stellenangebote"
CONFIG = "https://cs-assets.b-ite.com/klinikum-schloss-winnenden/jobs-api/main-listing.min.js"
API = "https://jobs.b-ite.com/api/v1/postings/search"
TENANT = "klinikum-schloss-winnenden:main-listing"
EMPLOYER = "c200e304-bf8e-4f50-bde5-39db6a0b8ab6"
DETAIL = "https://jobs.karriere.zfp-winnenden.de/jobposting/"


def _organization(value):
    return (isinstance(value, dict) and
            re.fullmatch(r"Klinikum Schlo(?:ß|ss) Winnenden", plain(value.get("name")), re.I))


def _identifier(value):
    return value.get("value") if isinstance(value, dict) else None


def _active(row):
    """The public search is not permission to display future/expired records."""
    now = datetime.now(timezone.utc)
    for field, future in (("startsOn", False), ("endsOn", True)):
        value = row.get(field)
        if not value and field == "endsOn":
            continue
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None or (stamp <= now if future else stamp > now):
                return False
        except (ValueError, TypeError, AttributeError):
            return False
    return True


def bite(source, req, get, report):
    # Never discover hosts, tenant IDs, endpoints or executable code from input.
    if source.key != "zfp_winnenden" or source.search != LISTING or source.api != API:
        raise FetchError("unsupported")
    final, html = get(LISTING, source)
    page = Selector(html)
    if (final != LISTING or TENANT not in page.css("[data-bite-jobs-api-listing]::attr(data-bite-jobs-api-listing)").getall()
            or "https://static.b-ite.com/jobs-api/loader-v1/api-loader-v1.min.js"
            not in page.css("script[src]::attr(src)").getall()):
        raise FetchError("unsupported")
    final, script = get(CONFIG, source, accept_javascript=True)
    # Public client identity is read afresh from this employer's fixed asset.
    # It is not a user secret and is neither stored nor returned to the client.
    keys = re.findall(r'\.createClient\(\{\s*key:\s*["\']([a-f0-9]{40})["\']\s*\}\)', script)
    if final != CONFIG or len(keys) != 1:
        raise FetchError("unsupported")
    final, text = get(API, source, accept_json=True, json_body={
        "key": keys[0], "channel": 0, "locale": "de", "origin": LISTING,
        "sort": {"by": "startsOn", "order": "desc"}, "offset": 0, "filter": {},
    })
    if final != API:
        raise FetchError("unsupported")
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise FetchError("unsupported") from None
    rows = data.get("jobPostings") if isinstance(data, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise FetchError("unsupported")
    terms = norm(req.q).split()
    rows = sorted(rows, key=lambda row: -sum(term in norm(str(row.get("title", ""))) for term in terms))
    seen, fetched = set(), 0
    for row in rows:
        ident, organization = row.get("id"), row.get("employer")
        raw = row.get("url")
        if (not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{40}", ident)
                or row.get("rootHash") != ident or raw != DETAIL + ident + "0"
                or not _organization(organization) or organization.get("uuid") != EMPLOYER
                or not _active(row)):
            report["filtered"] += 1
            continue
        if ident in seen:
            continue
        seen.add(ident)
        if fetched >= 10:
            break
        fetched += 1
        try:
            final, html = get(raw, source)
        except FetchError as error:
            if error.code != "gone":
                raise
            report["filtered"] += 1
            continue
        postings = []
        for script in Selector(html).css('script[type="application/ld+json"]::text').getall():
            try:
                postings.extend(entries(json.loads(script)))
            except (ValueError, TypeError):
                continue
        posting = postings[0] if len(postings) == 1 else {}
        employer = posting.get("hiringOrganization")
        job = None
        if (final == raw and _identifier(posting.get("identifier")) == ident and _organization(employer)
                and _identifier(employer.get("identifier")) == EMPLOYER
                and plain(posting.get("title")) == plain(row.get("title"))):
            job = extract(html, final, source, req.q)
        # Empty shells and metadata-only teasers are not concrete job evidence.
        if job and job.get("description"):
            yield job
        else:
            report["filtered"] += 1
