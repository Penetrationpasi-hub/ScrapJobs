# Scrapling-Stellensuche: begrenzter Admin-Pilot

## Umfang und aktueller Status

Zusätzliche Quelle neben JobSpy, Mistral, Apify, Google und BA. Keine bestehenden
Quellen werden ersetzt. Die vier ursprünglichen Pilotquellen bleiben erhalten:

| Quelle | Freigegebene Hostnamen im Pilot | Verfahren |
| --- | --- | --- |
| Indeed | de.indeed.com, www.indeed.com | Suchseite → Direktlinks mit Job-ID → JobPosting/konkrete DOM-Felder |
| StepStone | www.stepstone.de, stepstone.de | Suchseite → einzelne Stellenangebote-URL → JobPosting/konkrete DOM-Felder |
| Festo | jobs.festo.com | öffentliche Karrieresuche → /job/-Detailseite → JobPosting |
| Bosch | careers.smartrecruiters.com, jobs.smartrecruiters.com | BoschGroup-Karriereseite → BoschGroup-Detailanzeige → JobPosting |

### Regionale Arbeitgeber aus der Unternehmensliste

`employers.json` erfasst die Unternehmensliste nach ursprünglicher Zeilennummer.
MAHLE/MAHLE Aftermarket, die Rems-Murr-Kliniken und Frech sind jeweils
zusammengefasst; Bosch Murrhardt nutzt die bestehende Bosch-Quelle.
Der Katalog enthält 53 zusätzliche konfigurierte Arbeitgeberquellen und drei
ausdrücklich blockierte Profile. Zusammen mit den vier bisherigen Quellen werden
60 Profile angezeigt. Fünf Arbeitgeber ohne gefundenen öffentlichen Stellenmarkt
wurden auf ausdrücklichen Nutzerwunsch ausgelassen. Die ursprünglich gemeinsame letzte Zeile wurde auf
ausdrücklichen Wunsch in Hahn Automobile und Klingele getrennt.
„Konfiguriert“ ist **keine bestätigte Live-Funktion**:
robots.txt, Zugriffssperren, JavaScript und fehlende JobPosting-Daten können
weiterhin zum sichtbaren Abbruch führen. Die Recherche bestätigt offizielle
Portale und bei zahlreichen Quellen echte Detail-Linkmuster, nicht alle
Worker-Abrufe aus dem Render-Netz.

Beispiele der neuen Quellen: Mercedes-Benz, STIHL, MAHLE, Diakonie Stetten,
Robert Bosch Krankenhaus, Kärcher, Paulinenpflege, Stadt Schorndorf, Frech,
stoba, WIRmachenDRUCK, FESSMANN und PFISTERER. Alle konfigurierten Quellen
müssen weiterhin Titel und Arbeitgeber einer konkreten Einzelanzeige belegen.
Es werden keine Felder aus Unternehmensnamen oder URL-Slugs erfunden.
Initiativbewerbungen und Talentpools sind keine konkreten Vakanzen.

Die blockierten Profile bleiben deaktiviert und zeigen den jeweiligen Grund in der
App, statt Sammelseiten/PDFs als Jobs auszugeben. Blockierte Quellen werden durch
eine Freigabe nicht freigeschaltet. Irmscher Automobilbau, winwin Office Network AG,
PicksRaus, Falkenstein Industrieservice und LINK Chemie wurden nach erfolgloser
Suche nach offiziellen öffentlichen Stellenmärkten auf Nutzerwunsch entfernt.
Gleichnamige andere Unternehmen oder BA-Aggregate sind kein Ersatz.

### Nachbearbeitung der bisher offenen Arbeitgeber

**Helix-Korrektur für Kreissparkasse Waiblingen und Landratsamt Rems-Murr-Kreis:**
Die Kreissparkasse beginnt auf `/ksk/joblist`, nicht der allgemeinen Karriereseite.
Beide Portale verlinken Einzelanzeigen als `jobad?prj=…`; hierfür gelten jetzt
exakte Mandantenpfade und Projektpräfixe statt des unpassenden Slash-Musters.
Titel, Arbeitgeber und Ort stammen aus dem jeweiligen JobPosting-Datensatz.
Die Arbeitgebernamen werden zusätzlich gegen die konkrete Quelle geprüft.
Die zwei öffentlichen Listen und je eine echte Detailseite wurden abgerufen
und mit den Parsern lokal geprüft; das ersetzt keinen Live-Suchlauf aus Render.
Die Regressionstests laufen offline und prüfen auch falsche Mandanten,
fehlende Anzeigen-IDs, fremde Arbeitgeber, Initiativbewerbungen und Ablaufdaten.
Keine Browserausführung, zusätzlichen API-Dienste oder geänderten Abrufgrenzen.

**Volksbank Stuttgart:** Die offizielle Bank-Website verlinkt `/_/joblist`.
Das bisher konfigurierte `/tvbvbs/career` und dessen Unter-Stellenliste führen
nicht zu diesem aktuellen Stellenbestand. Die korrigierte Quelle akzeptiert nur
`/_/jobad?prj=100073P…` auf dem konkreten Volksbank-Host sowie JobPosting-Daten
mit Arbeitgeber `Volksbank Stuttgart eG`. Die öffentliche Liste enthielt bei der
Prüfung sieben Anzeigenlinks; eine echte Detailseite lieferte Titel, Arbeitgeber
und Ort. Diese lokale Originalseitenprüfung und die Offline-Regressionstests
sind kein Nachweis eines erfolgreichen Render-Suchlaufs.

Die folgenden zehn Anbindungen ergänzen die bisherigen 43 konfigurierten
Arbeitgeberquellen. Es handelt sich nicht nur um neue Linkmuster:

| Arbeitgeber | Auslesung / Nachweis |
| --- | --- |
| TTI / AEG / Milwaukee | Öffentliche Workday-Suche als read-only JSON-POST, anschließend konkrete JobPosting-Seiten |
| Mulfinger | Offizielle Karriere-Verknüpfung zu JOIN; genaue Mandanten- und Arbeitgeberprüfung |
| Stadtwerke Waiblingen | Öffentliche myjobboard-JSON-Liste und je ein Detaildatensatz; Mandant, ID, Public-Status, Arbeitgeber, Anschrift, Ablaufdatum |
| Dusyma | Offizielle Website muss das easyHR-Board weiter einbetten; Kunden-ID, Anzeigen-ID, online-Status und Absender nachgewiesen |
| RIANI | Shopware-Anzeigenseiten; realer Seitentitel und RIANI-Absender, keine aus Slugs gebauten Stellen |
| AWRM | TYPO3-Einzelanzeigen; realer Seitentitel und aus dem Anzeigentext extrahierter Arbeitgeber |
| BENZ Sport | Jede konkrete Anzeige auf der gemeinsamen Seite getrennt; belegter Publisher und eigene Text-Direktlinks |
| Eisenmann | Konkrete Akkordeonabschnitte getrennt; tatsächlicher Arbeitgeber Personal-Service, eigene Text-Direktlinks |
| Hahn Automobile | Die beiden offiziell verlinkten JSON-Kategorien Fachkräfte/Ausbildung; konkrete sopea-JobPosting-Seiten, keine Initiativ-Kategorie |
| Klingele | Offizieller SuccessFactors-Stellenmarkt, konkrete JobPosting-Seiten |

BENZ und Eisenmann bekommen keine erfundenen externen Einzelanzeigen-URLs.
Ihre separaten Anzeigenkarten verlinken per Browser-Textfragment zum belegten
Abschnitt auf der originalen Seite. Suchbegriff, Arbeitgeber und jeweiliger
Anzeigeninhalt werden einzeln geprüft; Nachbaranzeigen dürfen nicht in die
Beschreibung geraten.

Die öffentlichen JSON-Endpunkte sind ausschließlich serverseitig konfiguriert.
POST wird nur für Workdays Suchabfrage verwendet, nicht für Bewerbungen oder
Statistiken. Auch diese Aufrufe prüfen robots.txt, DNS/IP, Zertifikat, Zeit- und
Dokumentbudget. JSON-/POST-Redirects werden abgelehnt, Antwortgrößen bleiben
begrenzt. Es wird kein fremdes JavaScript ausgeführt.

Offline-Tests prüfen die recherchierten HTML- und JSON-Formate, falsche
Mandanten/Arbeitgeber, entfernte Anzeigen, robots-Sperren, POST-Weiterleitungen,
private IPs und die unveränderte Grenze von 30 Stellen/40 Dokumenten.
Zusätzlich wurden lokal bereits abgerufene öffentliche HTML-Beispiele mit den
Parsern geprüft. Das ist **kein vollständiger freigegebener Live-Lauf des
Render-Dienstes** und keine Aussage, dass alle anderen Quellen live geprüft sind.

**Nicht fertig / bewusst deaktiviert:**

- Signalhorn: öffentlich eingebettetes Prescreen-Widget identifiziert, sein
  Anbieter-Endpunkt jedoch nicht erreichbar. Die Karriereseite selbst enthält
  keine Stellen, sie lädt sie nur per Widget-Skript nach.
- BKZ / Murrhardter Zeitung (`bkz`): Der Samstags-Stellenmarkt ist nur eine
  eingebettete Blätter-PDF-Ansicht (Yumpu) ohne einzelne Anzeigen. Es gibt
  keinen auslesbaren Stellenmarkt; kein PDF-/OCR-Ersatz.

Diese Quelle ist keine „null offenen Stellen“-Aussage. Ein fehlender oder
nicht erreichbarer Stellenmarkt lässt sich nicht durch einen erfundenen Adapter
zuverlässig vervollständigen. Nach Bereitstellung erreichbarer Anzeigen kann
der Adapter ergänzt werden (für Signalhorn: Widget-Antwort von prescreen.io
nötig; der Host war auch bei der Wiederholung am 2026-11-07 nicht erreichbar).

**Murrelektronik (`murrelektronik`, Adapter `murr`):** Der frühere HTTP-500-Stellenmarkt
ist ersetzt durch die offizielle Liste
`www.murrelektronik.com/de/landingpages/karriere/stellenangebote/` mit
Einzelanzeigen unter `/detail/job/<slug>/` (am 2026-11-07 29 Links). Die Seiten
haben kein JobPosting; Titel stammt aus der einzigen Seitenüberschrift
(`h1.leadHeadline`), der Arbeitgeber nur aus den Corporation-Strukturdaten
(„Murrelektronik GmbH“). Ein Ort wird nur bei „Standort in …“ im Seitentext
übernommen. Initiativbewerbungen, abgelaufene und zu kurze Seiten entfallen.
`robots.txt` der www-Domain antwortet mit 301 auf eine HTML-Seite, ist also nicht
lesbar. **Nutzerbestätigte Ausnahme:** Nur dieser Fall (direktes 301 auf
`/robots.txt`) gilt für diese Quelle als „keine robots-Datei“, und nur für GET der
Liste und der `/detail/job/`-Seiten. Jede andere Quelle, 403/429/500 und
robots-Sperren bleiben Abbruch. Mit Offline-Tests auf synthetischen Seiten
geprüft, nicht in einem Render-Lauf. Freigabe: `murrelektronik` in
`SCRAPLING_APPROVED_SOURCES` (oder Gruppe `employers`).

Die App bietet einen Arbeitgeberfilter, einen Auswahlzähler und „Auswahl leeren“.
**Maximal vier Quellen je explizitem Lauf** bleiben auch serverseitig erzwungen.
Maximal 30 Anzeigen, 40 Dokumentabrufe, 240 Sekunden sowie die bisherigen
Tageskontingente bleiben unverändert. Ein Lauf fragt nicht alle Arbeitgeber ab.
Indizes ohne nachgewiesene serverseitige Suchparameter werden lokal nach
Suchbegriff in Linktext und URL priorisiert; das ist keine vollständige Suche
über alle offenen Stellen des Unternehmens.

**bluum Baden-Württemberg (`bluum_bw`):** Regionalbörse der Neuen Pressegesellschaft
(Stuttgarter Zeitung/Nachrichten, Südwest Presse) auf Jobiqo-Basis, wie
Rems-Murr-JOBS. Suche `bw.bluum.de/jobs?search=…` liefert 10 Treffer je Seite
direkt im HTML, der Pager hat kein `rel=next`, daher eigener Selektor. Die
Einzelanzeige hat ein `JobPosting` mit dem **echten Inserenten** als Arbeitgeber
(nicht der Verlag); die Beschreibung ist dort entity-escaped und wird in
`extraction.py` einmal entschlüsselt. Struktur an Originalseiten-Quelltext
geprüft (Startseite, Suche, Einzelanzeige). `robots.txt` (vom Nutzer geliefert):
`Allow: /`, `Crawl-delay: 10`, nur `/api/gmapi` gesperrt. Wegen der 10 s läuft bluum
wie Rems-Murr-JOBS **allein in einer eigenen Gruppe** (Worker, Netlify-Function
und App erzwingen das) und liest je Lauf höchstens drei Suchseiten und zehn
Anzeigen (`max_pages`/`max_details` am Katalogeintrag), damit das 240-Sekunden-Budget
reicht. **Ort und Umkreis:** bluum kennt keinen Ortsparameter in der URL (die Ortssuche ist eine
JavaScript-Autovervollständigung über `/api/gmapi`, per robots.txt gesperrt) und führt Anzeigen
aus ganz Deutschland. Der Worker liest deshalb den Ort jedes Treffers aus der Liste
(`teaser`/`teaser_location` am Katalogeintrag) und holt nur Einzelanzeigen, die laut
`geo.py` im Umkreis liegen; Mehrfachstandorte („…+“), fehlende und nicht auflösbare Orte
bleiben, die genaue Prüfung macht danach Netlify am Ort der Einzelanzeige. `geo.py` nutzt
`plz_de.txt`/`orte_de.txt`, erzeugt mit `node scripts/export-orte-worker.mjs` aus
`netlify/lib/orte-de.mjs`. Ein Live-Lauf aus Render steht aus. Aggregator: nur ausdrücklich per
`bluum_bw` freigeben, nicht über die Gruppe `employers`. Es werden keine Schlüssel aus dem Seitenquelltext
verwendet.

**jobsucheBW (`jobsuche_bw`):** Stellenportal von Nussbaum Medien für Baden-Württemberg
(`www.jobsuche-bw.de`, Next.js). Die Suche `/suchergebnis/?fulltext=…` liefert 25 Treffer
serverseitig im HTML (kein Pager-Link, deshalb `max_pages: 1`; gelesen werden ohnehin höchstens
10 Anzeigen). Einzelanzeigen liegen unter `/jobs/<id>/<titel>`, die ID ist entweder numerisch
(eigene Nussbaum-Anzeigen) oder `SDE-…`/`IDA-…` (Partnerportale). Beide Formen haben ein
`JobPosting` mit dem **echten Inserenten** als Arbeitgeber, Datum und Gültigkeit in ISO-Form.
Kein Ortsfilter, weil die Standortsuche eine interne `locationId` braucht; die Treffer sind
deshalb bundesweit (auch Anzeigen außerhalb von BW), Ort und Umkreis werden erst nachgelagert
anhand des ausgelesenen Standorts bewertet. `robots.txt` sperrt nur
`/job/drucken/`, `/bewerbung/`, `/followup/`, `/jpm-unsubscribe/` und `/firmenprofile/drucken/`,
kein `Crawl-delay`, daher normale Gruppe mit 1 s Abstand. Struktur an Originalseiten-Quelltext
geprüft (Startseite, Kategorieseite, Suche, zwei Einzelanzeigen); `robots.txt` wurde von
außerhalb des Workers gelesen, ein Live-Lauf aus Render steht aus. Aggregator: nur ausdrücklich
per `jobsuche_bw` freigeben, nicht über die Gruppe `employers` (`AGGREGATOR_SOURCES` in `sources.py`).

**Zeitungsverlag Waiblingen (`zvw`):** `karriere.zvw.de/stellenangebote/` ist eine
WordPress-Seite ohne eigenes Bewerbersystem; ihre Anzeigen sind feste Links auf
`rems-murr-jobs.de/job/…`. Der Eintrag liest diese Übersicht und übernimmt nur
Einzelanzeigen von `rems-murr-jobs.de` mit JobPosting und Arbeitgeber
„Zeitungsverlag … Waiblingen“ (Kurzauszug plus Originallink). robots.txt beider
Hosts wird wie bei allen Quellen geprüft; die Seite wurde nur als vom Nutzer
übermittelter Quelltext ausgewertet, nicht live aus dieser Umgebung. Der
Arbeitgebername im JobPosting ist noch nicht an einer Live-Anzeige bestätigt.
Weil die Anzeigen auf `rems-murr-jobs.de` (10 s `Crawl-delay`) liegen, läuft `zvw` wie Rems-Murr-JOBS
**allein in einer eigenen Gruppe** (`ISOLATED_SOURCES`). In Render `zvw` ausdrücklich zu
`SCRAPLING_APPROVED_SOURCES` ergänzen; die Gruppe `employers` schließt es nicht mehr ein.

### Aktualisierung des bestehenden Dienstes

1. Den neuen App-Stand von `main` manuell in Netlify deployen. Automatische
   Git-Deploys bleiben unverändert abgeschaltet.
2. Beim vorhandenen Render-Dienst den verwendeten Branch prüfen. Wurde er mit
   dem früheren Feature-Branch erstellt, in Render auf `main` umstellen und
   den neuesten Commit **manuell** deployen. Keinen zweiten Dienst erstellen.
3. Nach eigener Quellenfreigabe in Render `SCRAPLING_APPROVED_SOURCES` setzen:
   zum Beispiel `stihl,frech,paulinenpflege,pfisterer` für einzelne Arbeitgeber.
   Die Gruppe `employers` erlaubt sämtliche konfigurierten Arbeitgeber, aber
   **nicht** Indeed/StepStone und niemals offene Adapter. Für Arbeitgeber und
   beide Börsen lautet der ausdrücklich zu setzende Wert
   `indeed,stepstone,employers`. Keine automatische Freigabe durch Code-Deployment.
4. Nach Übernahme der Render-Einstellung in der App „Dienst verbinden /
   aufwecken“ wählen. Auswahl leeren, bis zu vier freigegebene Quellen auswählen
   und einen Suchlauf ausdrücklich starten.

Bestehende Tokens und die Netlify-Dienstadresse bleiben unverändert. Keine
Dienstadresse oder Tokenwerte ins Repo schreiben. Neue Quellen wurden nicht
automatisch gecrawlt oder als in Produktion getestet erklärt.

Die Hostnamen und Templates sind **Pilotkonfiguration, keine bestätigte Live-Abdeckung**.
Die Entwicklungstests benutzen synthetische Seiten; es wurden keine realen Suchabrufe
durchgeführt. Insbesondere Indeed/StepStone können HTTP-Zugriffe blockieren und
Bosch kann JavaScript benötigen. Das wird als Sperre beziehungsweise nicht unterstütztes
Seitenformat ausgewiesen, nicht durch erfundene Stellen oder einen anderen Anbieter ersetzt.

Vor Freischaltung die konkreten Domains, Nutzungsbedingungen, robots.txt und das
vorgesehene kleine Testbudget mit dem Betreiber abstimmen. Administratorstatus allein
ist keine Erlaubnis zum Crawlen beliebiger Websites. Login-Sperren und CAPTCHAs werden
nicht umgangen.

## Architektur

React → authentifizierte Netlify-Function `/api/scrapling-jobs` → eigener Python-Dienst.
Die Function prüft die aktuelle Adminrolle, bindet jeden Lauf an sein Konto und
reserviert ein eigenes begrenztes App-Kontingent. Diensttoken bleiben ausschließlich
serverseitig. Das Frontend bekommt keine direkte Worker-URL oder Zugangsdaten.

Scrapling 0.5 übernimmt das DOM-Parsing, CSS-/XPath-Auswahl und die Extraktion.
**Bewusste Sicherheitsentscheidung:** HTTP läuft nicht über den nativen Scrapling-Fetcher,
sondern über den kleinen gepinnten HTTPS-Transport. Er verbindet ausschließlich zur
vorab geprüften öffentlichen IP, erhält TLS-Hostprüfung und SNI und prüft jeden
Redirect neu. Dadurch gibt es keinen zweiten ungeschützten DNS-Aufruf.

Browserrendering, MCP, Proxyrotation und automatische CAPTCHA-Lösung sind deaktiviert.
Es entstehen daher keine Browser-Unteranfragen. Browserunterstützung erst separat
ergänzen, wenn gesicherter Egress einschließlich aller Unteranfragen bewiesen ist.

## Einrichtung nach eigener Hosting-Freigabe

### Bereitgestellter Pilot

Die Basisadresse des bereitgestellten Piloten aus der Render-Dienstübersicht
in Netlify als `SCRAPLING_API_URL` eintragen, ohne `/health` anzuhängen.
Den konkreten Variablenwert nicht in Repository-Dateien dokumentieren: Ist die
Variable in Netlify als geheim markiert, blockiert der Secret-Scanner auch
Fundstellen dieses Wertes in Dokumentation.
Der öffentliche Healthcheck hat mit HTTP 200 und dem erwarteten Dienstprotokoll
geantwortet. Das bestätigt nicht die Netlify-Tokenkonfiguration oder eine Freigabe
für Stellenabrufe. `SCRAPLING_ENABLED=1` und der passende `SCRAPLING_API_TOKEN`
bleiben serverseitige Hosting-Einstellungen; Dienstgeheimnisse gehören nicht ins Repo.

### Kostenlosen Render-Pilot starten

Der Nutzer hat die Vorbereitung des kostenlosen Render-Dienstes gewählt. Der
Blueprint allein erstellt noch keinen laufenden Dienst. Die folgende Anleitung
beschreibt die Einrichtung beziehungsweise die Wiederherstellung im eigenen
Render-Konto; der oben genannte Pilot wurde bereits bereitgestellt.

1. Zuerst die Hosting-Ergänzung in GitHub prüfen/mergen; im Repo muss die neue
   `render.yaml` vorhanden sein. Sie ist bewusst in gültiger JSON-/YAML-Syntax
   geschrieben und definiert genau einen Free-Web-Service, ohne Datenbank/Disk.
2. Auf https://dashboard.render.com/ **New → Blueprint** wählen, GitHub-Zugriff
   auf `Penetrationpasi-hub/N-chster-Schritt2` erlauben und dieses Repo auswählen.
   Die Blueprint-Datei liegt an der Repo-Wurzel, nicht im Worker-Unterordner.
3. Vor dem Bestätigen kontrollieren: Runtime **Python**, Instanz **Free**, nur der
   Scrapling-Pilot. Keine bezahlte Instanz oder Zusatzressource wählen. Render
   erzeugt das Dienstgeheimnis selbst; es steht nicht im Repository.
4. Den ersten Deploy abwarten. Aus der Render-Serviceübersicht die tatsächliche
   `https://…onrender.com`-Adresse kopieren. Nicht aus dem Servicenamen raten.
   `/health` muss `ok: true`, `service: naechster-schritt-scrapling`,
   `protocol: 1` und `browser: false` liefern.
5. In Render unter **Environment** den erzeugten Wert von `SCRAPLING_API_TOKEN`
   selbst in die sichere Netlify-Variable gleichen Namens übertragen. Nicht im
   Chat, Screenshot oder GitHub posten. In Netlify außerdem
   `SCRAPLING_API_URL` auf die kopierte Render-Basisadresse und
   `SCRAPLING_ENABLED` auf `1` setzen; Scope **Functions**, Kontext **Production**.
   Diese Werte sind ausschließlich serverseitig, niemals `VITE_…`.
6. Netlify neu deployen und, falls nötig, den Deploy veröffentlichen. In der
   App als Admin **Dienst verbinden / aufwecken** benutzen. Das macht begrenzte
   GET-Statusanfragen, keine Stellensuche und keine Budgetreservierung.
7. Zunächst bleiben alle Quellen mit **noch nicht freigegeben** sichtbar. Erst
   nach Vereinbarung einer konkreten Quelle und eines kleinen Live-Testbudgets
   `SCRAPLING_APPROVED_SOURCES` in Render setzen und die App erneut verbinden.
   Ohne diese Freigabe erfolgt kein Abruf einer Stellenwebsite.

**Free-Einschränkungen:** Nach 15 Minuten ohne eingehende Anfragen schläft der
Dienst; der Start dauert laut Render etwa eine Minute. Die App prüft nach
ausdrücklichem Klick bis ca. 90 Sekunden lang, höchstens zwölfmal und nur den
geschützten Quellenstatus. Token-/Konfigurationsfehler werden nicht als
Aufwärmen wiederholt. Ein gestarteter Such-POST wird niemals automatisch erneut
abgesetzt. Ein hängender Build oder falscher Host kann nicht durch Warten
repariert werden.

Free-Stunden werden mit anderen Free-Diensten im selben Render-Workspace geteilt.
Es gelten Grenzen für Bandbreite/Buildminuten; bei hinterlegter Zahlungsmethode
können laut Render Zusatzentgelte für Überschreitungen entstehen. Spend-Limits
und Zahlungsoptionen vor Bestätigung prüfen; keine kostenpflichtige Erweiterung
ist genehmigt. Auto-Deploys sind im Blueprint abgeschaltet; spätere Worker-Updates
müssen bewusst veröffentlicht werden. Kein künstlicher Dauer-Ping hält Free wach.

Ohne Blueprint sind dieselben Werte bei **New → Web Service** einzugeben:
Root Directory `scrapling-server`, Runtime Python 3, Build Command
`pip install --disable-pip-version-check -r requirements.txt`, Start Command wie
unten, Health Check `/health`, genau eine Free-Instanz. Python 3.13.11 einstellen,
ein eigenes starkes Dienstgeheimnis über die sicheren Server-Einstellungen setzen
und alle weiteren Variablen entsprechend dem Blueprint übernehmen.

Quellen: https://render.com/docs/free · https://render.com/docs/blueprint-spec ·
https://render.com/docs/deploy-fastapi

Python >= 3.10, ein einzelner Dienstprozess/eine Instanz. Die verfügbaren Ressourcen
und Kosten des Hosts vor Einrichtung bestätigen. Auf Replit keine Docker- oder
Virtualenv-Anleitung verwenden; Pakete mit der vorgesehenen Paketverwaltung einrichten.
Die fest gepinnten Abhängigkeiten stehen in requirements.txt.

Start aus scrapling-server:

```sh
uvicorn main:app --host 0.0.0.0 --port "$PORT" --workers 1 --limit-concurrency 8 --timeout-keep-alive 5
```

Worker-Konfiguration über die jeweiligen sicheren Server-Einstellungen:

- `SCRAPLING_ENABLED=1`: ausdrückliche Aktivierung; ohne diesen Wert abgeschaltet.
- `SCRAPLING_API_TOKEN`: eigenes starkes Dienstgeheimnis. Niemals im Repo oder Browser.
- `SCRAPLING_APPROVED_SOURCES`: einzeln freigegebene Quellen, kommagetrennt.
  Ohne Einträge führt auch ein eingeschalteter Worker **keine Website-Abrufe** aus.
- Optional `SCRAPLING_EMPLOYERS`: JSON-Liste mit ein bis dreißig Arbeitgeberkonfigurationen,
  jeweils key, label, hosts, search, detail und optional next_selector. Search ist eine
  feste HTTPS-URL mit `{q}` und `{location}`. hosts sind exakte erlaubte Zielhosts,
  detail ein auf die konkrete Anzeigenstruktur begrenzter regulärer Ausdruck.
  ATS-Zieldomains ausdrücklich mit aufnehmen, keine Wildcards. Die Liste ersetzt
  die beiden ursprünglichen Arbeitgebervorlagen, nicht den regionalen Katalog.
  Doppelte Quellenschlüssel sind ein Konfigurationsfehler.

Netlify-Konfiguration:

- `SCRAPLING_ENABLED=1`
- `SCRAPLING_API_URL`: feste HTTPS-Basisadresse des genehmigten Workers, keine
  URL-Parameter, Zugangsdaten oder Fragmente.
- `SCRAPLING_API_TOKEN`: dasselbe Dienstgeheimnis wie beim Worker.

Für Produktion ist ein genehmigter HTTPS-Dienst nötig. Es wurde weder ein Host
provisioniert noch ein kostenpflichtiges Abo eingerichtet. Vorhandene Replit-Secrets
sind kein Beleg für Netlify-Konfiguration. Kein automatisches Deployment; der
vorhandene Build-Ignore in netlify.toml bleibt unverändert.

## Limits und Fehler

- Pro Suche maximal 30 Anzeigen, maximal 10 Details je Quelle.
- Maximal zwei Suchseiten je Quelle und **40 Dokumentanfragen insgesamt**, inklusive
  robots.txt und sämtlicher Weiterleitungsschritte.
- Maximal 2 MiB je Antwort; komprimierte Antworten werden nicht unkontrolliert entpackt.
- Gesamtdeadline 240 Sekunden, durch separaten Abrufprozess auch bei blockierendem DNS
  erzwungen. Ein aktiver Lauf dienstweit; Quellen seriell, keine versteckte Parallelität.
- Mindestens eine Sekunde pro Host; strengere robots.txt-Crawl-delay/Request-rate gelten.
  Nicht prüfbare oder untersagende robots.txt führt zu keiner Seitenabfrage.
- Kein Retry nach 403/429, kein automatischer Ersatzanbieter und kein Auto-Crawl.
- Separates App-Kontingent: 10 Starts/Konto/UTC-Tag und 30 Starts global/UTC-Tag,
  **auch für Admins**, keine behauptete Anbieterrechnung und keine Erhöhung anderer Budgets.

JobPosting mit eindeutigem Titel und Arbeitgeber wird bevorzugt. Mehrere JobPostings
auf einer Seite, generische Karriereindizes, fehlender Arbeitgeber, abgelaufene
Anzeigen und Weiterleitungen auf Listen bleiben außen vor. Orte, Datum oder
Beschreibungen werden nie ergänzt/erfunden. Nicht verifizierbare Länder/Entfernungen
werden sichtbar gekennzeichnet; bekannte ausländische oder zu weit entfernte Orte
werden ausgefiltert. Die bestehende lokale Ortsdatenbank ist keine vollständige
Welt-Geokodierung; unbekannte Orte werden deshalb nicht als bestätigt eingeordnet.

## Laufzustand und Abschaltung

Start ist ein POST mit Idempotency-Key; Polling ist ein GET mit kontogebundener ID.
Identische Startanfragen starten keine zweite Suche. Ein unklar bestätigter Start
wird nicht wiederholt. Budgetreservierungen werden bei unklaren Fehlern beibehalten.
Lauf und Suchparameter sind in Netlify Blobs kontogebunden gespeichert. Fertige
Ergebnisse sind eine Stunde abrufbar, danach wird 410 geliefert und der abgerufene
Blobs-Eintrag gelöscht; keine Ablage von HTML. Unbesuchte alte Blobs-Einträge werden
nicht durch eine Hintergrundaufgabe physisch bereinigt und müssen in die
Betriebs-Aufbewahrungsrichtlinie aufgenommen werden. Der Worker liefert alte
Ergebnisse nach einer Stunde nicht mehr aus und räumt sie beim nächsten Start auf.
Worker-Neustart bedeutet sichtbaren Suchfehler, nicht automatische Neusuche.

Im Browser hält „Abfrage anhalten“ ausschließlich das Polling an. Der bereits
begrenzte Serverlauf läuft bis zu seinem Limit; „Status weiter abfragen“ startet
ihn nicht neu. Suchparameter-/Kontowechsel zeigt keine alten Ergebnisse.
Gespeicherte Stellen werden weiter durch die bestehenden Kontofunktionen verwaltet.

Abschaltung: SCRAPLING_ENABLED ungleich 1 auf der Function und/oder im Worker.
Bestehende Suchquellen bleiben verfügbar; gespeicherte Bewerbungen werden nicht
verändert. Für Worker-Shutdown muss ein aktiver Abrufprozess vom Host mitbeendet werden.

### Verbindungsfehler unterscheiden

- **Noch nicht eingerichtet:** Netlify-Konfiguration unvollständig oder ausgeschaltet.
- **Dienstanmeldung abgelehnt:** Token auf Render und Netlify vergleichen, ohne sie zu teilen.
- **Python-Dienst abgeschaltet:** Aktivierung und Diensttoken auf Render prüfen.
- **Wird aufgeweckt:** Kurz warten; die begrenzte Prüfung betrifft nur `/sources`.
- **Keine passende Antwort:** Falsche URL, fehlgeschlagener Worker-Build oder falscher Dienst.
- **Verbunden, keine Quelle freigegeben:** Infrastruktur funktioniert; Live-Freigabe steht aus.

Der öffentliche Healthcheck beweist nur die Erreichbarkeit des richtigen Prozesses.
Er ersetzt nicht die Prüfung des geschützten `/sources` mit übereinstimmendem Token
und nicht einen separat genehmigten echten Stellenabruf.

## Tests ohne Live-Provider

Aus dem App-Verzeichnis:

```sh
npm run test:scrapling
npm test
npm run typecheck
npm run build
```

Isolierter Browser-Testserver:

```sh
npx vite --config tests/preview/vite.config.ts --host 0.0.0.0
```

Dieser explizite Test-Config ersetzt Clerk und APIs mit festen Testantworten, blockiert
externe fetch-Anfragen und verwendet nur die Konten scrapling-browser-admin/normal.
Er ist **keine Authentifizierungsoption der Produktions-App** und darf nicht als
Produktions-Startkommando konfiguriert werden. Die normale vite.config.ts importiert
keinen Testcode. `/stellen?testRole=normal` prüft die ausgeblendete Adminoberfläche;
Suchbegriffe mit „Leer“/„Gesperrt“ liefern entsprechende simulierte Zustände.
