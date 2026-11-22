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

1. `.github/workflows/sammeln.yml` startet täglich (und per Hand über *Run workflow*). GitHub führt geplante
   Läufe oft Stunden verspätet aus; gesammelt wird deshalb beim ersten geplanten Lauf eines Berliner
   Kalendertags, weitere Läufe am selben Tag werden übersprungen.
2. Zuerst laufen die Tests, dann `scrapling-server/batch.py`.
3. `batch.py` ruft für jede Quelle dieselbe `crawl()`-Logik auf wie der Live-Dienst, nur im
   **Katalogmodus**: ohne Suchbegriff und Ort und **vollständig** – gefiltert wird erst in der App.
   Die Grenzen (5000 Stellen/Einzelanzeigen, 100 Ergebnisseiten, 6000 Abrufe je Quelle) sind nur Sicherungen.
   Zeitbudget 900 s je Quelle (Börsen mit 10 s Crawl-Delay und Sitemaps doppelt, PFISTERER vierfach);
   ist es erschöpft, zählt das bis dahin Gelesene („teilweise: timeout nach N Stellen“). Nach 5 h Gesamtzeit
   beginnt der Lauf keine neue Quelle mehr; diese behalten ihre Stellen aus dem Vorlauf.
   **Bundesweite Sitemaps** (persona, Lidl, Kaufland): alle Anzeigen im Suchgebiet **150 km um Waiblingen**
   (`AREA` in `batch.py`), Anzeigen ohne erkennbaren Ort zählen mit; je Portal bis zu 1 h.
4. Danach wird `stellen.json` zusammengeführt und zusammen mit `STELLEN.md` und
   [`stellen.xlsx`](stellen.xlsx) committet.

**`stellen.xlsx`** (aus `scrapling-server/excel.py`) zeigt den aktuellen Stand zum schnellen Prüfen:
Blatt *Übersicht* mit Datenstand und Warnung, wenn die Daten älter als ein Tag sind; *Stellen* mit allen
Anzeigen (grün = im letzten Lauf neu, orange = Quelle zuletzt nicht gelesen); *Quellen* mit dem Status je Arbeitgeber.

**Fehlende robots.txt:** Antwortet ein Host auf `/robots.txt` mit 404 oder 410, gelten im Katalog-Lauf
keine Regeln, und die öffentliche Karriereseite wird normal abgerufen (weiterhin mit mindestens 1 s Abstand).
Ebenso gelten keine Regeln, wenn der Server statt einer robots.txt seine normale HTML-Seite liefert oder die Datei
nur Sitemap-Zeilen enthält. Sperr- und Captcha-Seiten zählen nicht dazu.
Alles andere bleibt Abbruch: 403/429, Serverfehler, Timeouts und jedes `Disallow`. Mit `--strict-robots` ist die alte strenge Regel wieder aktiv. Der Live-Dienst (`main.py`) ist davon nicht betroffen.

Es bleiben alle übrigen Schutzmaßnahmen des bisherigen Codes aktiv: robots.txt (wo vorhanden), `Crawl-delay`,
mindestens 1 s Abstand je Host (auch zwischen Quellen desselben Hosts), nur HTTPS auf
festgelegten Hosts, DNS-/IP-Prüfung, Größen- und Zeitgrenzen, kein JavaScript, kein Browser.

## Welche Quellen

Alle konfigurierten Arbeitgeber aus `scrapling-server/employers.json` und `sources.py`.
Standardmäßig **ausgeschlossen**: Indeed, StepStone, bluum BW, jobsucheBW und Trabajo.org
(bundesweite Börsen, ohne Suchbegriff nur Rauschen) sowie die zwei deaktivierten Profile
(Signalhorn, BKZ). Änderbar über `SCRAPJOBS_EXCLUDE` (ersetzt die Liste) oder
`SCRAPJOBS_SOURCES` (nur diese Quellen), lokal und im Workflow-Dialog.

**Trabajo.org** (`trabajo`) ist eine bundesweite Börse mit serverseitig gerenderter Suche
(`/stellenangebote-<begriff>/<ort>`, weitere Seiten über `?page=N`). Ohne Suchbegriff liest der Katalog
die Ortsliste `/stellenangebote/<Ort>` je `catalog_locations` (Waiblingen, Schorndorf, Backnang,
Winnenden, Fellbach, Schwaikheim, Murrhardt, Welzheim), nicht die bundesweite Liste. Der Adapter liest
den Ort je Treffer und ruft nur Anzeigen im Umkreis einzeln ab; der Umkreis wird nochmals an der
verifizierten JobPosting-Adresse geprüft. Arbeitgeber ist der echte Inserent, nicht Trabajo. Wie
jobsucheBW nur mit ausdrücklicher Freigabe (`SCRAPJOBS_SOURCES=trabajo` bzw.
`SCRAPLING_APPROVED_SOURCES`), nie über die Gruppe `employers`.
Im Katalog gelten je Ort vier Suchseiten und bis zu 100 Einzelanzeigen innerhalb des
Abrufbudgets; das ist eine begrenzte Auswahl, kein vollständiger Export aller Portalstellen.
Die Live-Suche behält ihre Grenzen von drei Seiten und zehn Einzelanzeigen.

Rems-Murr-JOBS und ZVW haben 10 s Crawl-Delay und laufen zuletzt.

**Globale Konzernportale** (Festo, MAHLE, Kärcher) listen ohne Suchbegriff weltweit. Für sie gibt es `catalog_locations`
(in `employers.json`, bei Festo in `sources.py`): Der Katalog fragt die Suche je Ort einmal mit `locationsearch=<Ort>` ab
und führt die Treffer zusammen. Je Ort wird vollständig gelesen (alle Ergebnisseiten). Aktuell Festo: Esslingen, Ostfildern · Kärcher: Winnenden, Schwaikheim ·
MAHLE: Stuttgart, Fellbach, Markgröningen, Kornwestheim, Mühlacker. Schlägt ein Ort fehl, zählen die übrigen,
und `quellen[].detail` nennt den fehlenden Ort. Die Orte gelten nur im Katalog, nicht in der Live-Suche.
Frühere weltweite Treffer verschwinden nach der Karenzzeit (3 Tage) von selbst.

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

## Eigenes Render-Projekt (optional)

`scrapling-server/` ist eine Kopie des Dienstes aus dem App-Repo (`N-chster-Schritt2`) plus `batch.py`.
**Das ist Absicht:** ScrapJobs läuft als eigenes Projekt, der „normale“ Scraper in der App bleibt
unverändert als Alternative bestehen. Der Katalog selbst braucht Render nicht, er läuft nur in GitHub Actions.

Wer die Live-Suche auch aus diesem Repo betreiben will, legt in Render einen **neuen** Web Service
aus diesem Repo an (*New → Blueprint*, nutzt `render.yaml`, Dienstname `scrapjobs-scrapling`,
eigener `SCRAPLING_API_TOKEN`, automatische Deploys aus). Der Dienst im App-Repo wird dafür nicht angefasst.

Einzige Änderung an `crawler.py` gegenüber dem Original: optionale Request-Attribute
`max_jobs`, `max_details`, `seconds`, `documents`. Ohne sie gelten die bisherigen Pilot-Limits
(30 Stellen, 40 Abrufe, 240 s, 10 Details). Änderungen an Adaptern müssen in beiden Repos
nachgezogen werden, solange beide Kopien existieren.

## Welche Quelle liefert was? (`laeufe.csv`, Blätter *Läufe* und *Ohne Ergebnis*)

Jeder Lauf hängt je Quelle eine Zeile an [`laeufe.csv`](laeufe.csv) an: Adapter, Status, **in diesem Lauf gelesene
Stellen** (`stellen_lauf`, bei Fehlern 0 – anders als `anzahl` in `stellen.json`, das alte Stellen stehen lässt),
davon neu, Stand im Katalog und Detail. `stellen.xlsx` zeigt das als Matrix Quelle × letzte 30 Läufe (rot = 0) und
als Arbeitsliste *Ohne Ergebnis* (Status, Detail, Läufe in Folge, letzter Erfolg).

**Roter Lauf:** Der letzte Schritt `scrapling-server/pruefen.py` lässt den Lauf fehlschlagen, sobald eine Quelle
0 Stellen geliefert hat (Fehlerstatus oder `done` ohne Stellen). Die Daten werden vorher committet; die Tabelle der
betroffenen Quellen steht in der Zusammenfassung des Laufs unter *Actions*. Dauerhaft nicht lauffähige Quellen stehen
mit Begründung in `scrapling-server/ohne_stellen_ok.json` und zählen nicht. Wird eine Quelle repariert (oder
bekommt sie wieder Stellen), erscheint ein Hinweis: dann aus der Liste streichen. Ein Test stellt sicher, dass dort
nur Quellen des Katalogs stehen.

**Wiederholung:** Quellen, die im Hauptdurchlauf mit einem vorübergehenden Fehler ausfallen (Timeout, Netzwerkfehler,
5xx, robots.txt nicht lesbar), werden bis zu zweimal erneut abgefragt (nach 90 s und nach weiteren 180 s;
`collect_with_retry` in `batch.py`); nur ein Erfolg ersetzt das erste Ergebnis. Für langsame Portale gilt ein längeres Zeitlimit je Abruf (`SLOW_REQUESTS`). Bleibt eine Quelle auch
danach ohne Stellen, steht im Detail „auch nach N Wiederholungen“ und der Lauf wird rot. Liefert eine Quelle `done`
ohne Stellen, nennt das Detail die Zahlen (z. B. „0 Stellen: 120 Adressen gelesen, 0 passend, 0 verworfen“).
