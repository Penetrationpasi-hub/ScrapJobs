import os
import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import geo
from extraction import discovery, extract, is_detail, plain
from safe_http import Budget, FetchError, Transport, USER_AGENT, RUN_SECONDS
from sources import registry, approved_sources
from employer_adapters import adapter_jobs
from robots_exceptions import missing_robots_scope, missing_robots_statuses
from search_outcomes import festo_no_matches


def crawl(req, transport_factory=Transport):
    # Live search keeps the pilot limits; the catalog batch passes its own via optional request attributes.
    max_jobs = getattr(req, "max_jobs", 30)
    total_documents = getattr(req, "documents", 40)
    custom = hasattr(req, "seconds") or hasattr(req, "documents")
    budget = Budget(getattr(req, "seconds", RUN_SECONDS), total_documents) if custom else Budget()
    transport = transport_factory(budget)
    sources = registry()
    approved = approved_sources(sources)
    jobs, reports, seen = [], [], set()
    robots = {}

    def allowed_get(raw, source, **options):
        def check_robots(current):
            host = urlsplit(current).hostname
            if host not in source.hosts:
                raise FetchError("unsafe_target")
            if host not in robots:
                try:
                    probe = {"robots_request": True} if missing_robots_scope(current, source, options) else {}
                    _, text = transport.get(f"https://{host}/robots.txt", source.hosts, **probe)
                except FetchError as error:
                    if missing_robots_scope(current, source, options) and error.http_status in missing_robots_statuses(source):
                        robots[host] = None
                        return
                    raise FetchError("robots_unavailable") from error
                if not re.search(r"(?im)^\s*user-agent\s*:", text):
                    raise FetchError("robots_unavailable")
                robot = RobotFileParser()
                robot.parse(text.splitlines())
                robots[host] = robot
            robot = robots[host]
            if robot is None:
                if not missing_robots_scope(current, source, options):
                    raise FetchError("robots_unavailable")
                return
            if not robot.can_fetch(USER_AGENT, current):
                raise FetchError("robots_denied")
            delay = robot.crawl_delay(USER_AGENT) or robot.crawl_delay("*") or 1
            rate = robot.request_rate(USER_AGENT) or robot.request_rate("*")
            if rate and rate.requests > 0:
                delay = max(delay, rate.seconds / rate.requests)
            last = transport.last.get(host, 0)
            if last and delay > 1:
                pause = max(0, last + delay - time.monotonic())
                if pause >= budget.deadline - time.monotonic():
                    raise FetchError("timeout")
                time.sleep(pause)
        final, html = transport.get(raw, source.hosts, authorize=check_robots, **options)
        if not options.get("accept_json") and ("captcha" in plain(html[:50000]).lower() or "access denied" in plain(html[:50000]).lower()):
            raise FetchError("blocked")
        return final, html

    for key in req.sources:
        source = sources[key]
        report = {"source": key, "label": source.label, "status": "done", "kept": 0, "filtered": 0}
        reports.append(report)
        if not source.available:
            report["status"] = "not_configured"
            continue
        if key not in approved:
            report["status"] = "not_approved"
            continue
        if len(jobs) >= max_jobs:
            report["status"] = "result_limit"
            continue
        try:
            if time.monotonic() >= budget.deadline:
                raise FetchError("timeout")
            if source.adapter != "html":
                for job in adapter_jobs(source, req, allowed_get, report):
                    if job["url"] in seen:
                        continue
                    seen.add(job["url"])
                    jobs.append(job)
                    report["kept"] += 1
                    if len(jobs) >= max_jobs:
                        break
                if report["filtered"] and not report["kept"]:
                    report["status"] = "no_verified_jobs"
                continue
            start = source.start(req.q, req.location)
            if key == "stepstone" and not req.location:
                start = start.replace("/in-", "")
            next_url = start
            details, visited = [], set()
            near = None
            if source.teaser and req.location and (origin := geo.center(req.location)):
                near = lambda place: geo.in_range(origin, place, req.radius_km)
            for _ in range(source.max_pages):
                if not next_url or next_url in visited:
                    break
                visited.add(next_url)
                final, html = allowed_get(next_url, source)
                if festo_no_matches(html, source, req.q):
                    if not details:
                        report["status"] = "no_matches"
                    break
                links, following = discovery(html, final, source, req.q, near)
                details.extend(link for link in links if link not in details)
                next_url = following
                # With a place filter further list pages are only worth their crawl delay while detail slots are free.
                if near and len(details) >= getattr(req, "max_details", source.max_details):
                    break
            # Rank across both discovered pages, not only within each page.
            terms = req.q.casefold().split()
            details.sort(key=lambda link: -sum(term in link.casefold() for term in terms))
            if not details:
                # An empty rendered shell is not proof of zero vacancies.
                if report["status"] != "no_matches":
                    report["status"] = "unsupported"
            for url in details[:getattr(req, "max_details", source.max_details)]:
                if len(jobs) >= max_jobs:
                    break
                if url in seen:
                    continue
                seen.add(url)
                try:
                    final, html = allowed_get(url, source)
                except FetchError as error:
                    if error.code == "gone":
                        report["filtered"] += 1
                        continue
                    raise
                job = extract(html, final, source, req.q) if is_detail(final, source) else None
                if job:
                    jobs.append(job)
                    report["kept"] += 1
                else:
                    report["filtered"] += 1
            if details and report["filtered"] and not report["kept"]:
                report["status"] = "no_verified_jobs"
        except FetchError as error:
            report["status"] = error.code
        except Exception:
            report["status"] = "unsupported"
    return {"status": "done", "jobs": jobs, "sources": reports, "documents": total_documents - budget.remaining}
