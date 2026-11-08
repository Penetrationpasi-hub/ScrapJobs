# Änderungen für die Live-Suche (N-chster-Schritt2 / scrapling-server)

Diese Datei fasst zusammen, was in diesem Repo gegenüber dem ursprünglichen Stand des App-Repos geändert wurde.
Der fertige Diff liegt in `uebernahme-live-suche.patch` (Pfade `scrapling-server/…`, passt auf das App-Repo):

```bash
cd N-chster-Schritt2
git apply --check /pfad/zu/uebernahme-live-suche.patch   # trockener Lauf
git apply /pfad/zu/uebernahme-live-suche.patch
```

Falls `employers.json` im App-Repo inzwischen anders aussieht, schlägt der Teil fehl. Dann die Einträge unten von Hand übernehmen.
`batch.py`, `.github/` und `render.yaml` gehören nur zum Sammler und werden nicht übernommen.

## Neue Leser (Adapter), neue Dateien
| Datei | Quelle | Was sie tut |
|---|---|---|
| `dvinci_adapter.py` | WIRmachenDRUCK | liest die DvinciData-Stellenliste (JSON im HTML) |
| `rems_adapter.py` | REMS | liest die Orchard-Listenseite |
| `personio_adapter.py` | RIVA / Mpire | liest den öffentlichen Personio-XML-Feed (`/xml`); lehnt DOCTYPE/ENTITY ab, IDs müssen numerisch sein |

Dazu: `employer_adapters.adapter_jobs` ruft `dvinci`, `rems_list`, `personio` auf. `sources.py` kennt die Adapter-Namen und bindet sie fest:
`rems_list` nur an Schlüssel `rems`, `personio` nur an einen Host `*.jobs.personio.de` mit `api = https://{host}/xml`.

## Geänderte Leser
- **Workday** (`employer_adapters.workday`): übernimmt `?locations=<32 Hex>` aus der Such-Adresse als `appliedFacets`, blättert bis zur Anzeigengrenze (`req.max_details`, sonst 10 wie bisher). TESAT und Airbus laufen darüber.
- **Mikrodaten** (`extraction.py`: `has_microdata`, `microdata`, `stamp`): SuccessFactors-Seiten (MAHLE, Festo, Kärcher, Klingele) haben kein JSON-LD, sondern `itemprop`-Mikrodaten. Genau eine JobPosting-Struktur, Titel notfalls aus `og:title`, abgelaufene `validThrough` werden verworfen.

## Transport (`safe_http.py`)
- `FetchError(code, http_status=None, detail=None)`: Diagnose-Texte (Content-Type, Netzfehler, DNS).
- Option `accept_xml` (nur `application/xml`, `text/xml`; keine Weiterleitungen).
- gzip wird begrenzt entpackt, auch wenn `identity` verlangt war (Stadt Waiblingen).
- `robots.txt` darf `text/txt` sein (Peter Hahn).

## Crawler (`crawler.py`)
Rückwärtskompatibel, die Live-Suche verhält sich ohne die neuen Request-Felder wie bisher:
- BOM am Anfang der robots.txt wird entfernt (sicher, kann immer gelten).
- Diagnose: `report["detail"]`, `report["sample"]`, Detailtext bei „Host nicht freigegeben".
- Captcha-Prüfung wird bei `accept_xml` übersprungen.
- **Nur Katalog-Lauf, NICHT für die Live-Suche übernehmen:** `robots_missing_ok` (fehlende oder Standard-robots.txt gilt als „keine Regeln"). Ohne das Request-Feld bleibt der Dienst streng. Ebenso die optionalen Felder `max_jobs`, `max_details`, `seconds`, `documents`, `max_pages`.

## Quellen (`employers.json`)
- `wirmachendruck` → `"adapter":"dvinci"`
- `rems` → `"adapter":"rems_list"`
- `riva` → `"adapter":"personio","api":"https://mpire.jobs.personio.de/xml"`
- `tesat` → `"adapter":"workday","api":"https://ag.wd3.myworkdayjobs.com/wday/cxs/ag/Airbus/jobs"`, `detail` `^/de-DE/Airbus/job/[^?#]+`
- neu `airbus` (gleiche API, drei Standort-IDs, `company_pattern` `airbus`)
- `soehnle` → Selektoren statt strukturierter Daten (`title_selector`, `company_selector`, `company_capture`, `company_pattern`, `description_selector`)
- `catalog_locations` (nur Katalog: Festo, MAHLE, Kärcher) wird von der Live-Suche nicht gebraucht.

## Tests
Neue Tests: `test_dvinci.py`, `test_rems_list.py`, `test_personio.py`, `test_microdata.py` (und ein Workday-Facettentest in `test_employer_adapters.py`).
Nach der Übernahme `python -m pytest -q` in `scrapling-server` ausführen.

## Noch offen
Die Firmennamen aus Workday tragen eine interne Nummer („922E Airbus …"). Das Entfernen steht noch aus.
