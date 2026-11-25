"""Katalog-Lauf: alle freigegebenen Arbeitgeber seriell abfragen und in stellen.json schreiben.

Nutzt dieselbe crawl()-Logik, dieselben Adapter sowie dieselbe robots.txt- und
Sicherheitsprüfung wie der Live-Dienst (main.py), nur ohne Suchbegriff und ohne
die engen Live-Limits. Es werden ausschließlich Metadaten veröffentlicht, keine
Anzeigentexte.

    python batch.py --out ../stellen.json
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import geo
import safe_http
from crawler import crawl
from retail_region import AREA_KM, AREA_NAME
from safe_http import Transport
from sources import AGGREGATOR_SOURCES, ISOLATED_SOURCES, registry

# Bundesweite Börsen/Aggregatoren: ohne Suchbegriff und Ortsfilter nur Rauschen.
DEFAULT_EXCLUDED = {"indeed", "stepstone", "bluum_bw", *AGGREGATOR_SOURCES}
SCHEMA = 1
# Der Katalog soll jede Quelle vollständig lesen; gefiltert wird erst in der App. Die Grenzen sind deshalb nur
# Sicherungen gegen Endlosschleifen, keine Auswahl: Stellen, Einzelanzeigen, Ergebnisseiten und Abrufe je Quelle.
CATALOG_JOBS = 5000
CATALOG_DETAILS = 5000
CATALOG_PAGES = 100
CATALOG_DOCUMENTS = 6000
# Umkreis des Katalogs (Mittelpunkt, km): die Arbeitsmarktanalyse im Repo Jobs rechnet jede Stelle zum Umkreis
# Waiblingen, Stellen außerhalb würden sie verfälschen. Stuttgart (~7 km) liegt darin.
AREA = (AREA_NAME, AREA_KM)
# Bundesweite Anzeigen-Sitemaps (tausende Anzeigen, je Anzeige ein Abruf): nur Anzeigen im Umkreis werden
# abgerufen, ohne Suchbegriff. Ohne erkennbaren Ort zählt eine Anzeige dort nicht (bundesweites Portal).
AREA_SOURCES = {"persona", "lidl", "kaufland"}
# Phenom kann direkt nach Koordinaten suchen; Catalent nutzt dasselbe Gebiet, aber das normale Zeitbudget.
AREA_SEARCH_SOURCES = AREA_SOURCES | {"catalent"}
AREA_SECONDS = 3600
# Ortsangaben, die auf einen Standort im Ausland deuten (Stellen ohne auflösbaren deutschen Ort).
FOREIGN = re.compile(r"\b(?:CH|AT|BE|FR|GB|UK|ES|IT|NL|PL|CZ|US|CN|Schweiz|Österreich|Belgien|Frankreich|Spanien|"
                     r"Italien|Niederlande|Polen|Tschechien|Vereinigtes Königreich|United Kingdom|USA|China)\b")
# Gesamtzeit des Laufs (s): danach werden keine weiteren Quellen mehr begonnen, damit das Ergebnis vor dem
# Workflow-Timeout gespeichert wird. Nicht mehr gelesene Quellen behalten ihre Stellen aus dem Vorlauf.
RUN_SECONDS = 5 * 3600
# Quellen, deren robots.txt lange Wartezeiten zwischen Abrufen verlangt (PFISTERER: 10 s): Faktor auf das Zeitbudget.
# dm: rund 270 Einzelanzeigen, im Live-Lauf 894 s (Budget je Quelle sonst 900 s).
SLOW_SOURCES = {"pfisterer": 4, "dm": 3}
# Zeitlimit (s) je einzelnem Abruf, wo 8 s zu knapp sind (langsame Portale, grosse Sitemaps).
# dm: Jobs-Sitemap rund 1 MB; mit 8 s lief sie am 23./24.11.2026 auf dem Runner in den Timeout.
SLOW_REQUESTS = {"db_audiotechnik": 20, "dm": 30, "ksk_waiblingen": 15, "volksbank_stuttgart": 15, "landratsamt_rmk": 15}
# Vorübergehende Fehler: die Quelle wird nach dem Hauptdurchlauf einmal wiederholt.
TRANSIENT = {"network_error", "upstream_error", "timeout", "robots_unavailable"}
# Pausen (s) vor der 1. und 2. Wiederholung.
RETRY_PAUSES = (90, 180)
# Mindestwartezeit (s) zwischen Abrufen, wenn der Server zu schnelle Abfragen mit 403/429 beantwortet.
# deinjob.diakonie-stetten.de sperrte am 22.11.2026 nach rund 75 schnellen Abrufen mit HTTP 403 (zwei volle
# Läufe binnen 20 Minuten). Deshalb 2 s Abstand und höchstens so viele Anzeigen wie vor dem Wegfall der Grenzen.
# ALDI SÜD und dm rufen je rund 270-400 Einzelanzeigen nacheinander ab.
MIN_DELAY = {"diakonie_stetten": 2, "aldi_sued": 2, "dm": 2}
# Quellen mit fester Obergrenze an Stellen bzw. Einzelanzeigen je Lauf (statt der Katalog-Grenzen).
SOURCE_LIMITS = {"diakonie_stetten": 60}
FIELDS = ("id", "title", "company", "location", "url", "posted")


def select_sources(configured, only=None, exclude=None):
    """Quellen des Katalogs: verfügbar, nicht ausgeschlossen, optional eingeschränkt."""
    excluded = DEFAULT_EXCLUDED if exclude is None else set(exclude)
    keys = [key for key, source in configured.items() if source.available and key not in excluded]
    if only:
        unknown = set(only) - set(configured)
        if unknown:
            raise ValueError("Unbekannte Quellen: " + ", ".join(sorted(unknown)))
        keys = [key for key in only if configured[key].available]
    # Börsen mit langem Crawl-Delay zuletzt, damit ein Hänger die übrigen nicht aufhält.
    return sorted(keys, key=lambda key: key in ISOLATED_SOURCES)


def make_transport_factory():
    """Ein gemeinsamer Zeitstempel je Host, damit der Abstand auch zwischen Quellen desselben Hosts gilt."""
    last = {}

    def factory(budget):
        transport = Transport(budget)
        transport.last = last
        return transport
    return factory


def record(job, key, label):
    row = {field: job.get(field) or "" for field in FIELDS}
    row["source"] = key
    row["sourceLabel"] = label
    return row


def merge(previous, results, today, now, grace_days=3, known=None):
    """Neuen Lauf mit dem Vorstand zusammenführen.

    results: {key: {"label", "status", "jobs": [...]}}.
    Nur Quellen mit Status "done" gelten als erfolgreich gelesen. Bei allen anderen
    bleibt der Vorstand unverändert stehen (Fehler ist kein "keine Stellen mehr").
    Bei erfolgreichen Quellen bleibt eine nicht mehr gesehene Anzeige noch grace_days
    stehen, weil Reihenfolge und Abrufgrenzen zwischen Läufen schwanken können.
    """
    old_jobs = {row["id"]: row for row in (previous or {}).get("stellen", []) if isinstance(row, dict) and row.get("id")}
    old_sources = {row["key"]: row for row in (previous or {}).get("quellen", []) if isinstance(row, dict) and row.get("key")}
    cutoff = (date.fromisoformat(today) - timedelta(days=grace_days)).isoformat()
    jobs, sources = {}, []
    for key, result in results.items():
        label = result["label"]
        old_here = {i: r for i, r in old_jobs.items() if r.get("source") == key}
        info = {"key": key, "label": label, "status": result["status"]}
        if result["status"] == "done":
            for job in result["jobs"]:
                row = record(job, key, label)
                before = old_here.get(row["id"], {})
                row["erstmalsGesehen"] = before.get("erstmalsGesehen") or today
                row["zuletztGesehen"] = today
                jobs[row["id"]] = row
            for ident, row in old_here.items():
                if ident not in jobs and (row.get("zuletztGesehen") or "") >= cutoff:
                    jobs[ident] = row
            info["letzterErfolg"] = today
        else:
            jobs.update(old_here)
            info["letzterErfolg"] = old_sources.get(key, {}).get("letzterErfolg")
        if result.get("detail"):
            info["detail"] = result["detail"]
        info["anzahl"] = sum(1 for row in jobs.values() if row["source"] == key)
        sources.append(info)
    # Teillauf: Quellen, die in diesem Lauf nicht abgefragt wurden, behalten Stand und Status unverändert.
    # Entfernt werden nur Quellen, die es im Katalog (known) nicht mehr gibt.
    for key, old in old_sources.items():
        if key in results or (known is not None and key not in known):
            continue
        sources.append(dict(old))
        jobs.update({i: r for i, r in old_jobs.items() if r.get("source") == key})
    if known is not None:
        position = {key: index for index, key in enumerate(known)}
        sources.sort(key=lambda info: position.get(info["key"], len(position)))
    ordered = sorted(jobs.values(), key=lambda r: (r["company"].casefold(), r["title"].casefold(), r["id"]))
    return {"schema": SCHEMA, "aktualisiert": now.isoformat(timespec="seconds"),
            "quellen": sources, "stellen": ordered}


HISTORY_FIELDS = ["lauf", "datum", "quelle", "label", "adapter", "status",
                  "stellen_lauf", "neu", "im_katalog", "detail"]


def append_history(path, now, results, previous, katalog, configured):
    """Je Quelle eine Zeile in laeufe.csv: was hat dieser Lauf wirklich geliefert?

    stellen_lauf = in diesem Lauf gelesene Stellen (bei Fehlern 0, auch wenn
    der Katalog die alten Stellen stehen laesst); neu = davon vorher nicht
    im Katalog; im_katalog = Stand des Katalogs nach dem Lauf.
    """
    old_ids = {}
    for row in (previous or {}).get("stellen", []):
        if isinstance(row, dict) and row.get("id"):
            old_ids.setdefault(row.get("source"), set()).add(row["id"])
    rows = []
    for key, result in results.items():
        ids = {job.get("id") for job in result["jobs"] if job.get("id")}
        rows.append({
            "lauf": now.isoformat(timespec="seconds"),
            "datum": now.date().isoformat(),
            "quelle": key,
            "label": result["label"],
            "adapter": getattr(configured.get(key), "adapter", "") or "",
            "status": result["status"],
            "stellen_lauf": len(result["jobs"]),
            "neu": len(ids - old_ids.get(key, set())),
            "im_katalog": katalog.get(key, 0),
            "detail": (result.get("detail") or "")[:200],
        })
    exists = Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
    return rows


def overview(catalog):
    """Lesbare Übersicht (Markdown) für die GitHub-Ansicht des Repos."""
    lines = ["# Stellenkatalog", "",
             f"Stand: {catalog['aktualisiert']} · {len(catalog['stellen'])} Stellen aus "
             f"{sum(1 for q in catalog['quellen'] if q['status'] == 'done')} von {len(catalog['quellen'])} Quellen", "",
             "## Quellen", "", "| Quelle | Status | Stellen | Letzter Erfolg | Detail |", "| --- | --- | ---: | --- | --- |"]
    for q in catalog["quellen"]:
        lines.append(f"| {q['label']} | {q['status']} | {q['anzahl']} | {q.get('letzterErfolg') or '–'} | {q.get('detail') or ''} |")
    lines += ["", "## Stellen", ""]
    by_company = {}
    for row in catalog["stellen"]:
        by_company.setdefault(row["company"], []).append(row)
    for company in sorted(by_company, key=str.casefold):
        lines += [f"### {company}", ""]
        for row in by_company[company]:
            place = f" · {row['location']}" if row["location"] else ""
            title = row["title"].replace("[", "(").replace("]", ")")
            lines.append(f"- [{title}]({row['url']}){place} · seit {row['erstmalsGesehen']}")
        lines.append("")
    return "\n".join(lines)


def area_distance(origin, place):
    """Entfernung (km) zum nächsten erkennbaren Ort; Fallback auf einzelne Wörter („Winnenden BW DE“), None wenn unbekannt."""
    distance = geo.distance_km(origin, place)
    if distance is not None:
        return distance
    found = [geo.distance_km(origin, word) for word in re.findall(r"[A-ZÄÖÜ][\wäöüß.-]{2,}", place or "")
             if geo.norm(word) not in geo.REGION_WORDS]
    found = [value for value in found if value is not None]
    return min(found) if found else None


def in_area(row, origin=None):
    """Stelle im Umkreis AREA? Unbekannter Ort zählt bei regionalen Arbeitgebern, nicht bei bundesweiten Portalen
    und nicht bei Standorten im Ausland."""
    origin = origin or geo.center(AREA[0])
    place = row.get("location") or ""
    distance = area_distance(origin, place)
    if distance is not None:
        return distance <= AREA[1]
    return row.get("source") not in AREA_SEARCH_SOURCES and not FOREIGN.search(place)


def keep_area(results, previous):
    """Stellen außerhalb des Umkreises aus dem Lauf und aus dem Vorstand entfernen; Zahl je Quelle im Detail."""
    origin = geo.center(AREA[0])
    for key, result in results.items():
        kept = [job for job in result["jobs"] if in_area({**job, "source": key}, origin)]
        dropped = len(result["jobs"]) - len(kept)
        if dropped:
            note = f"{dropped} außerhalb {AREA[1]} km um {AREA[0]}"
            result["detail"] = (result["detail"] + " · " + note) if result.get("detail") else note
        result["jobs"] = kept
    if previous:
        previous = {**previous, "stellen": [row for row in previous.get("stellen", [])
                                            if not isinstance(row, dict) or in_area(row, origin)]}
    return results, previous


def source_seconds(key, source, options):
    """Zeitbudget je Quelle bzw. je Ort; Börsen mit langem Crawl-Delay und Sitemaps bekommen mehr."""
    if key in AREA_SOURCES:
        return max(options.seconds, AREA_SECONDS)
    factor = 2 if key in ISOLATED_SOURCES or getattr(source, "adapter", "") == "sitemap" else 1
    return options.seconds * factor * SLOW_SOURCES.get(key, 1)


def collect(keys, configured, options, factory=None, sleep=time.sleep, log=print, deadline=None):
    factory = factory or make_transport_factory()
    results = {}
    for index, key in enumerate(keys):
        source = configured[key]
        if deadline is not None and time.monotonic() >= deadline:
            results[key] = {"label": source.label, "status": "timeout", "jobs": [],
                            "detail": "Gesamtzeit des Laufs erschöpft, Quelle nicht mehr gelesen"}
            log(f"{key}: timeout (Gesamtzeit erschöpft)")
            continue
        # Globale Konzernportale werden je Ort einzeln abgefragt (catalog_locations), bundesweite Sitemaps im
        # Suchgebiet (AREA), alle anderen einmal ohne Ort.
        area = key in AREA_SEARCH_SOURCES
        places = (AREA[0],) if area else tuple(getattr(source, "catalog_locations", ())) or ("",)
        jobs, seen, failures, done, detail = [], set(), [], 0, None
        started = time.monotonic()
        cap = SOURCE_LIMITS.get(key, options.max_jobs + options.max_details + options.documents)
        for place in places:
            seconds = source_seconds(key, source, options)
            if deadline is not None:
                seconds = max(1, min(seconds, deadline - time.monotonic()))
            req = SimpleNamespace(q="", location=place, radius_km=AREA[1] if area else 25, sources=[key],
                                  max_jobs=min(options.max_jobs, cap), max_details=min(options.max_details, cap),
                                  max_pages=options.max_pages, documents=min(options.documents, cap + 10),
                                  robots_missing_ok=not options.strict_robots,
                                  min_delay=MIN_DELAY.get(key, 0),
                                  request_timeout=SLOW_REQUESTS.get(key, 8),
                                  seconds=seconds)
            try:
                outcome = crawl(req, factory)
                report = outcome["sources"][0]
            except Exception as error:  # eine kaputte Quelle darf den Lauf nicht beenden
                report, outcome = {"status": "worker_error"}, {"jobs": []}
                log(f"  ! {key} {place}: {type(error).__name__}")
            if report["status"] in {"timeout", "request_limit", "blocked", "result_limit", "incomplete"} and outcome["jobs"]:
                # Zeit- oder Abrufbudget mitten in einer großen Quelle erschöpft: Gelesenes zählt, Rest im Detail.
                failures.append((place, f"{report['status']} nach {len(outcome['jobs'])} Stellen"))
                report = {**report, "status": "done"}
            if report["status"] == "done":
                done += 1
                for job in outcome["jobs"]:
                    if job["url"] not in seen:
                        seen.add(job["url"])
                        jobs.append(job)
            else:
                failures.append((place, report["status"]))
                detail = detail or report.get("detail") or (
                    f"verworfen, z. B. {report['sample']}" if report.get("sample") else None)
            if place:
                log(f"  {key} [{place}]: {report['status']}, {len(outcome['jobs'])} Stellen")
        if done:
            status = "done"
            if failures:  # Teilergebnis: gelesene Orte zählen, die übrigen stehen im Detail
                detail = "teilweise: " + ", ".join(f"{place or key} {state}" for place, state in failures)
            elif not jobs:
                # Gelesen, aber leer: Zahlen mitgeben, damit sichtbar ist, woran es liegt.
                parts = []
                if "urls" in report:
                    parts.append(f"{report['urls']} Adressen gelesen, {report.get('matched', 0)} passend")
                parts.append(f"{report.get('filtered', 0)} verworfen")
                detail = "0 Stellen: " + ", ".join(parts) + (f" · {report['detail']}" if report.get("detail") else "")
            else:
                detail = None
        else:
            status = failures[0][1]
        results[key] = {"label": source.label, "status": status, "jobs": jobs, "detail": detail}
        log(f"{key}: {status}, {len(jobs)} Stellen, {time.monotonic() - started:.0f}s" + (f" ({detail})" if detail else ""))
        if index + 1 < len(keys):
            sleep(options.pause)
    return results


def collect_with_retry(keys, configured, options, factory=None, sleep=time.sleep, log=print, pauses=RETRY_PAUSES,
                       deadline=None):
    """Hauptdurchlauf, danach bis zu zweimal die Quellen mit vorübergehendem Fehler wiederholen.

    GitHub-Runner erreichen einzelne Portale zeitweise nicht (Timeout, 5xx, robots.txt nicht lesbar);
    Wiederholungen nach einer Pause beheben das meist. Ein Erfolg ersetzt den Fehlschlag; sonst bleibt
    das erste Ergebnis, mit dem Hinweis, wie oft es erneut versucht wurde.
    """
    results = collect(keys, configured, options, factory=factory, sleep=sleep, log=log, deadline=deadline)
    tries = {}
    for pause in pauses:
        again = [key for key in keys if results[key]["status"] in TRANSIENT]
        if not again or (deadline is not None and time.monotonic() + pause >= deadline):
            break
        log(f"\nWiederholung nach {pause} s: {', '.join(again)}")
        sleep(pause)
        second = collect(again, configured, options, factory=factory, sleep=sleep, log=log, deadline=deadline)
        for key in again:
            tries[key] = tries.get(key, 0) + 1
            if second[key]["status"] == "done":
                results[key] = second[key]
    for key, count in tries.items():
        if results[key]["status"] in TRANSIENT:
            first = results[key]
            suffix = f" (auch nach {count} Wiederholung{'en' if count > 1 else ''})"
            first["detail"] = ((first.get("detail") or first["status"]) + suffix)[:200]
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="../stellen.json", help="Zieldatei, zugleich Vorstand für die Zusammenführung")
    parser.add_argument("--sources", default=os.environ.get("SCRAPJOBS_SOURCES", ""),
                        help="Kommagetrennte Quellenschlüssel; leer = alle Arbeitgeber des Katalogs")
    parser.add_argument("--exclude", default=os.environ.get("SCRAPJOBS_EXCLUDE"),
                        help="Kommagetrennt; ersetzt die Standard-Ausschlussliste (indeed, stepstone, bluum_bw, jobsuche_bw)")
    parser.add_argument("--max-details", type=int, default=CATALOG_DETAILS, help="Einzelanzeigen je Quelle")
    parser.add_argument("--max-jobs", type=int, default=CATALOG_JOBS, help="Stellen je Quelle")
    parser.add_argument("--max-pages", type=int, default=CATALOG_PAGES, help="Ergebnisseiten je Quelle")
    parser.add_argument("--documents", type=int, default=CATALOG_DOCUMENTS, help="Abrufe je Quelle")
    parser.add_argument("--seconds", type=int, default=900,
                        help="Zeitbudget je Quelle (Börsen mit 10 s Crawl-Delay und Sitemaps doppelt, Suchgebiet-Sitemaps 1 h)")
    parser.add_argument("--run-seconds", type=int, default=RUN_SECONDS, help="Gesamtzeit des Laufs")
    parser.add_argument("--max-body-mb", type=int, default=8, help="Größte erlaubte Antwort (Live-Dienst: 2 MB)")
    parser.add_argument("--pause", type=float, default=2.0, help="Sekunden Pause zwischen Quellen")
    parser.add_argument("--strict-robots", action="store_true",
                        help="Auch bei fehlender robots.txt (404) abbrechen; Standard: ohne Datei gelten keine Regeln")
    parser.add_argument("--grace-days", type=int, default=3)
    options = parser.parse_args(argv)

    previous_limit, safe_http.MAX_BODY = safe_http.MAX_BODY, options.max_body_mb * 1024 * 1024
    try:
        return run(options)
    finally:
        safe_http.MAX_BODY = previous_limit


def run(options):
    configured = registry()
    only = [part.strip() for part in options.sources.split(",") if part.strip()]
    exclude = None if options.exclude is None else [part.strip() for part in options.exclude.split(",") if part.strip()]
    keys = select_sources(configured, only, exclude)
    # Das Tor ist die Katalogliste selbst; die Freigabe der Live-Suche (Render) bleibt davon getrennt.
    os.environ["SCRAPLING_APPROVED_SOURCES"] = ",".join(keys)

    out = Path(options.out)
    try:
        previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    except ValueError:
        previous = None
    print(f"{len(keys)} Quellen")
    results = collect_with_retry(keys, configured, options, deadline=time.monotonic() + options.run_seconds)
    # Nur Stellen im Umkreis (AREA) in den Katalog, auch aus dem Vorstand.
    results, previous = keep_area(results, previous)
    now = datetime.now(timezone.utc)
    history = out.with_name("laeufe.csv")
    if not any(r["status"] == "done" for r in results.values()):
        stand = {}
        for row in (previous or {}).get("stellen", []):
            stand[row.get("source")] = stand.get(row.get("source"), 0) + 1
        append_history(history, now, results, previous, stand, configured)
        print("Keine Quelle erfolgreich gelesen; stellen.json bleibt unverändert.", file=sys.stderr)
        return 1
    catalog = merge(previous, results, now.date().isoformat(), now, options.grace_days, known=list(configured))
    append_history(history, now, results, previous, {q["key"]: q["anzahl"] for q in catalog["quellen"]}, configured)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(out)
    out.with_name("STELLEN.md").write_text(overview(catalog), encoding="utf-8")
    ok = sum(1 for r in results.values() if r["status"] == "done")
    print(f"{len(catalog['stellen'])} Stellen aus {ok}/{len(keys)} Quellen -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
