import json
import os
import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import geo
from scrapling import Selector
from extraction import discovery, entries, extract, is_detail, plain
from safe_http import Budget, FetchError, Transport, USER_AGENT, RUN_SECONDS
from sources import registry, approved_sources
from employer_adapters import adapter_jobs
from robots_exceptions import missing_robots_scope, missing_robots_statuses
from search_outcomes import festo_no_matches


def probe(html):
    """Kurzbeschreibung einer verworfenen Anzeigenseite für die Diagnose; Inhalte werden nicht übernommen."""
    try:
        page = Selector(html)
        scripts = page.css('script[type="application/ld+json"]::text').getall()
        postings = 0
        for script in scripts:
            try:
                postings += sum(1 for _ in entries(json.loads(script)))
            except (ValueError, TypeError):
                continue
        title = plain(page.css("title::text").get() or "")[:50]
    except Exception:
        return "(Seite nicht lesbar)"
    return f"(ld+json {len(scripts)}, JobPosting {postings}, {len(html)} Zeichen, Titel «{title}»)"


def crawl(req, transport_factory=Transport):
    # Live search keeps the pilot limits; the catalog batch passes its own via optional request attributes.
    max_jobs = getattr(req, "max_jobs", 30)
    # Nur der Katalog-Lauf: eine fehlende robots.txt (404/410) heißt "keine Regeln veröffentlicht".
    # Der Live-Dienst bleibt streng; 403/429/5xx, Timeouts und Sperren brechen immer ab.
    robots_missing_ok = getattr(req, "robots_missing_ok", False)
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
                raise FetchError("unsafe_target", detail=f"Host nicht freigegeben: {host}")
            if host not in robots:
                try:
                    probe = {"robots_request": True} if missing_robots_scope(current, source, options) else {}
                    _, text = transport.get(f"https://{host}/robots.txt", source.hosts, **probe)
                except FetchError as error:
                    if missing_robots_scope(current, source, options) and error.http_status in missing_robots_statuses(source):
                        robots[host] = None
                        return
                    if robots_missing_ok and error.code == "gone":
                        robots[host] = None
                        return
                    raise FetchError("robots_unavailable") from error
                text = text.lstrip("\ufeff")  # BOM am Dateianfang verdeckt sonst die erste Zeile
                if not re.search(r"(?im)^\s*user-agent\s*:", text):
                    # Keine Regeln: Standardseite der Website statt einer robots.txt (HTML-200) oder eine Datei nur mit
                    # Sitemap-Zeilen. Sperr- und Captcha-Seiten zählen nicht dazu.
                    if robots_missing_ok and not re.search(
                            r"captcha|access denied|just a moment|cf-chl|attention required|enable javascript|forbidden",
                            text[:5000], re.I):
                        robots[host] = None
                        return
                    raise FetchError("robots_unavailable", detail="robots.txt ohne User-agent-Zeile: «" + " ".join(text.split())[:120] + "»")
                robot = RobotFileParser()
                robot.parse(text.splitlines())
                robots[host] = robot
            robot = robots[host]
            if robot is None:
                if not (robots_missing_ok or missing_robots_scope(current, source, options)):
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
                    raise FetchError("timeout", detail=f"robots.txt verlangt {delay:g}s Wartezeit zwischen Abrufen ({host})")
                time.sleep(pause)
        final, html = transport.get(raw, source.hosts, authorize=check_robots, **options)
        if not options.get("accept_json") and not options.get("accept_xml") and ("captcha" in plain(html[:50000]).lower() or "access denied" in plain(html[:50000]).lower()):
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
            for _ in range(getattr(req, "max_pages", source.max_pages)):
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
                        report.setdefault("sample", url + " (nicht gefunden)")
                        continue
                    raise
                why = []
                job = extract(html, final, source, req.q, why=why) if is_detail(final, source) else None
                if not job and not why:
                    why.append("Weiterleitung auf " + final)
                if job:
                    jobs.append(job)
                    report["kept"] += 1
                else:
                    report["filtered"] += 1
                    if "sample" not in report:
                        report["sample"] = url + " " + probe(html) + " → " + "; ".join(why)
            if details and report["filtered"] and not report["kept"]:
                report["status"] = "no_verified_jobs"
        except FetchError as error:
            report["status"] = error.code
            # Ursache für die Diagnose: bei robots_unavailable z. B. "HTTP 404" oder "blocked".
            cause = error.__cause__ if isinstance(error.__cause__, FetchError) else error
            if cause.detail:
                report["detail"] = cause.detail
            elif cause.http_status or cause is not error:
                report["detail"] = cause.code + (f" HTTP {cause.http_status}" if cause.http_status else "")
        except Exception:
            report["status"] = "unsupported"
    return {"status": "done", "jobs": jobs, "sources": reports, "documents": total_documents - budget.remaining}
