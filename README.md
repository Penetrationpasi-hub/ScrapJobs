# ScrapJobs

Täglicher Stellenkatalog regionaler Arbeitgeber im Rems-Murr-Kreis und Umgebung.
GitHub Actions liest jeden Morgen die Karriereseiten der freigegebenen Arbeitgeber
und schreibt das Ergebnis nach [`stellen.json`](stellen.json). Die App liest nur
diese Datei, es gibt kein Backend, keinen Deploy und keinen Scraping-Aufruf zur Suchzeit.

```
https://raw.githubusercontent.com/Penetrationpasi-hub/ScrapJobs/main/stellen.json
```

(`raw.githubusercontent.com` liefert die nötigen CORS-Header mit.)

## Ablauf

1. `.github/workflows/sammeln.yml` startet täglich gegen 05 Uhr (und per Hand über *Run workflow*).
2. Zuerst laufen die Tests, dann `scrapling-server/batch.py`.
3. `batch.py` ruft für jede Quelle dieselbe `crawl()`-Logik auf wie der Live-Dienst, nur im
   **Katalogmodus**: ohne Suchbegriff und Ort, ohne die engen Live-Limits
   (25 Einzelanzeigen, 90 Abrufe, 300 s je Quelle; Börsen mit 10 s Crawl-Delay bekommen doppelt Zeit).
4. Danach wird `stellen.json` zusammengeführt und committet.

Es bleiben alle Schutzmaßnahmen des bisherigen Codes aktiv: robots.txt, `Crawl-delay`,
mindestens 1 s Abstand je Host (auch zwischen Quellen desselben Hosts), nur HTTPS auf
festgelegten Hosts, DNS-/IP-Prüfung, Größen- und Zeitgrenzen, kein JavaScript, kein Browser.

## Welche Quellen

Alle konfigurierten Arbeitgeber aus `scrapling-server/employers.json` und `sources.py`.
Standardmäßig **ausgeschlossen**: Indeed, StepStone, bluum BW und jobsucheBW
(bundesweite Börsen, ohne Suchbegriff nur Rauschen) sowie die zwei deaktivierten Profile
(Signalhorn, BKZ). Änderbar über `SCRAPJOBS_EXCLUDE` (ersetzt die Liste) oder
`SCRAPJOBS_SOURCES` (nur diese Quellen), lokal und im Workflow-Dialog.

Rems-Murr-JOBS und ZVW haben 10 s Crawl-Delay und laufen zuletzt.

## Datenformat

Nur Metadaten, **keine Anzeigentexte** (das Repo ist öffentlich). Den Volltext holt die App
bei Bedarf selbst von der Originalseite.

```json
{
  "schema": 1,
  "aktualisiert": "2026-11-09T03:41:12+00:00",
  "quellen": [
    {"key": "stihl", "label": "STIHL", "status": "done", "letzterErfolg": "2026-11-09", "anzahl": 14}
  ],
  "stellen": [
    {
      "id": "scrapling-1a2b3c…", "title": "…", "company": "…", "location": "…",
      "url": "https://…", "posted": "2026-11-03",
      "source": "stihl", "sourceLabel": "STIHL",
      "erstmalsGesehen": "2026-11-05", "zuletztGesehen": "2026-11-09"
    }
  ]
}
```

**„Noch aktuell“:**

- Eine Quelle zählt nur bei Status `done` als erfolgreich gelesen. Bei jedem anderen Status
  (Timeout, robots gesperrt, `unsupported` …) bleibt ihr alter Stand unverändert stehen:
  ein Fehler ist kein „keine Stellen mehr“. `quellen[].status` und `letzterErfolg` zeigen das.
- Bei erfolgreichen Quellen bleibt eine nicht mehr gesehene Anzeige noch 3 Tage stehen
  (`--grace-days`), weil Reihenfolge und Abrufgrenzen zwischen Läufen schwanken.
  Die App kann zusätzlich `zuletztGesehen` gegen das aktuelle Datum prüfen.
- Schlägt **jede** Quelle fehl, wird `stellen.json` nicht angefasst und der Lauf schlägt rot fehl.

## Lokal ausführen

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r scrapling-server/requirements.txt pytest
cd scrapling-server
python -m pytest -q
python batch.py --sources stihl,kaercher --out ../stellen.json
```

## Live-Suche (Render) und Umzug

`scrapling-server/` ist eine unveränderte Kopie des Dienstes aus dem App-Repo
(`N-chster-Schritt2`), plus `batch.py`. Die einzige Änderung an `crawler.py`:
optionale Request-Attribute `max_jobs`, `max_details`, `seconds`, `documents`;
ohne sie gelten die bisherigen Pilot-Limits (30 Stellen, 40 Abrufe, 240 s, 10 Details).

Solange Render noch aus dem App-Repo deployt, existiert der Code an zwei Stellen.
Empfehlung: Render auf dieses Repo umstellen (`rootDir: scrapling-server`, siehe `render.yaml`
im App-Repo) und den Ordner dort entfernen. Bis dahin Änderungen an Adaptern in beiden Repos nachziehen.
