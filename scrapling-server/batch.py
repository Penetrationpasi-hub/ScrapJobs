"""Katalog-Lauf: alle freigegebenen Arbeitgeber seriell abfragen und in stellen.json schreiben.

Nutzt dieselbe crawl()-Logik, dieselben Adapter sowie dieselbe robots.txt- und
Sicherheitsprüfung wie der Live-Dienst (main.py), nur ohne Suchbegriff und ohne
die engen Live-Limits. Es werden ausschließlich Metadaten veröffentlicht, keine
Anzeigentexte.

    python batch.py --out ../stellen.json
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from crawler import crawl
from safe_http import Transport
from sources import AGGREGATOR_SOURCES, ISOLATED_SOURCES, registry

# Bundesweite Börsen/Aggregatoren: ohne Suchbegriff und Ortsfilter nur Rauschen.
DEFAULT_EXCLUDED = {"indeed", "stepstone", "bluum_bw", *AGGREGATOR_SOURCES}
SCHEMA = 1
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


def merge(previous, results, today, now, grace_days=3):
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
        info["anzahl"] = sum(1 for row in jobs.values() if row["source"] == key)
        sources.append(info)
    # Quellen, die in diesem Lauf nicht vorkamen (z. B. aus der Liste genommen), werden entfernt.
    ordered = sorted(jobs.values(), key=lambda r: (r["company"].casefold(), r["title"].casefold(), r["id"]))
    return {"schema": SCHEMA, "aktualisiert": now.isoformat(timespec="seconds"),
            "quellen": sources, "stellen": ordered}


def overview(catalog):
    """Lesbare Übersicht (Markdown) für die GitHub-Ansicht des Repos."""
    lines = ["# Stellenkatalog", "",
             f"Stand: {catalog['aktualisiert']} · {len(catalog['stellen'])} Stellen aus "
             f"{sum(1 for q in catalog['quellen'] if q['status'] == 'done')} von {len(catalog['quellen'])} Quellen", "",
             "## Quellen", "", "| Quelle | Status | Stellen | Letzter Erfolg |", "| --- | --- | ---: | --- |"]
    for q in catalog["quellen"]:
        lines.append(f"| {q['label']} | {q['status']} | {q['anzahl']} | {q.get('letzterErfolg') or '–'} |")
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


def collect(keys, configured, options, factory=None, sleep=time.sleep, log=print):
    factory = factory or make_transport_factory()
    results = {}
    for index, key in enumerate(keys):
        label = configured[key].label
        req = SimpleNamespace(q="", location="", radius_km=25, sources=[key],
                              max_jobs=options.max_jobs, max_details=options.max_details,
                              documents=options.documents,
                              seconds=options.seconds * (2 if key in ISOLATED_SOURCES else 1))
        started = time.monotonic()
        try:
            outcome = crawl(req, factory)
            report = outcome["sources"][0]
            results[key] = {"label": label, "status": report["status"], "jobs": outcome["jobs"]}
        except Exception as error:  # eine kaputte Quelle darf den Lauf nicht beenden
            results[key] = {"label": label, "status": "worker_error", "jobs": []}
            log(f"  ! {key}: {type(error).__name__}")
        log(f"{key}: {results[key]['status']}, {len(results[key]['jobs'])} Stellen, {time.monotonic() - started:.0f}s")
        if index + 1 < len(keys):
            sleep(options.pause)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="../stellen.json", help="Zieldatei, zugleich Vorstand für die Zusammenführung")
    parser.add_argument("--sources", default=os.environ.get("SCRAPJOBS_SOURCES", ""),
                        help="Kommagetrennte Quellenschlüssel; leer = alle Arbeitgeber des Katalogs")
    parser.add_argument("--exclude", default=os.environ.get("SCRAPJOBS_EXCLUDE"),
                        help="Kommagetrennt; ersetzt die Standard-Ausschlussliste (indeed, stepstone, bluum_bw, jobsuche_bw)")
    parser.add_argument("--max-details", type=int, default=25, help="Einzelanzeigen je Quelle")
    parser.add_argument("--max-jobs", type=int, default=60, help="Stellen je Quelle")
    parser.add_argument("--documents", type=int, default=90, help="Abrufe je Quelle")
    parser.add_argument("--seconds", type=int, default=300, help="Zeitbudget je Quelle (Börsen mit 10 s Crawl-Delay doppelt)")
    parser.add_argument("--pause", type=float, default=2.0, help="Sekunden Pause zwischen Quellen")
    parser.add_argument("--grace-days", type=int, default=3)
    options = parser.parse_args(argv)

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
    results = collect(keys, configured, options)
    now = datetime.now(timezone.utc)
    if not any(r["status"] == "done" for r in results.values()):
        print("Keine Quelle erfolgreich gelesen; stellen.json bleibt unverändert.", file=sys.stderr)
        return 1
    catalog = merge(previous, results, now.date().isoformat(), now, options.grace_days)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(out)
    out.with_name("STELLEN.md").write_text(overview(catalog), encoding="utf-8")
    ok = sum(1 for r in results.values() if r["status"] == "done")
    print(f"{len(catalog['stellen'])} Stellen aus {ok}/{len(keys)} Quellen -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
