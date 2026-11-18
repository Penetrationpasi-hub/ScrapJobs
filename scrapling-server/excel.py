"""stellen.json -> stellen.xlsx: aktueller Stand zum schnellen Pruefen.

    python excel.py ../stellen.json ../stellen.xlsx

Blaetter: Uebersicht (Stand, Frische, Zahlen), Stellen (alle, mit Filter
und Link), Quellen (Status je Arbeitgeber). Alle Werte fest eingetragen,
keine Formeln, damit auch Vorschau-Apps am Handy alles anzeigen.
"""

import csv
import json
import os
import sys
from datetime import date, datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

KOPF_FONT = Font(bold=True, color="FFFFFF")
KOPF_FILL = PatternFill("solid", start_color="1D3C6E")
WARN_FILL = PatternFill("solid", start_color="FCE4D6")
FEHL_FILL = PatternFill("solid", start_color="F4B6B6")
GRAU_FILL = PatternFill("solid", start_color="D9D9D9")
MAX_LAEUFE = 30
NEU_FILL = PatternFill("solid", start_color="E2EFDA")
DATUM = "DD.MM.YYYY"


def _datum(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _kopf(ws, spalten, breiten):
    ws.append(spalten)
    for i, b in enumerate(breiten, start=1):
        c = ws.cell(row=1, column=i)
        c.font, c.fill = KOPF_FONT, KOPF_FILL
        ws.column_dimensions[get_column_letter(i)].width = b
    ws.freeze_panes = "A2"


def build(doc, heute=None, laeufe=None, ausnahmen=None):
    heute = heute or datetime.now(timezone.utc).date()
    laeufe = laeufe or []
    ausnahmen = ausnahmen or {}
    stand_dt = doc.get("aktualisiert") or ""
    stand = _datum(stand_dt)
    quellen = doc.get("quellen") or []
    stellen = doc.get("stellen") or []
    status = {q.get("key"): q.get("status") for q in quellen}
    ok = [q for q in quellen if q.get("status") == "done"]
    alter = (heute - stand).days if stand else None

    wb = Workbook()
    ue = wb.active
    ue.title = "Übersicht"
    ue.column_dimensions["A"].width = 34
    ue.column_dimensions["B"].width = 70
    zeilen = [
        ("Stellenkatalog ScrapJobs", None),
        ("Datenstand (letzter Lauf)", stand_dt.replace("T", " ")[:16] + " UTC"
         if stand_dt else "unbekannt"),
        ("Alter der Daten", f"{alter} Tage" if alter is not None else "?"),
        ("Stellen", len(stellen)),
        ("davon neu im letzten Lauf",
         sum(1 for s in stellen if _datum(s.get("erstmalsGesehen")) == stand)),
        ("Arbeitgeber mit Stellen", len({s.get("source") for s in stellen})),
        ("Quellen gelesen", f"{len(ok)} von {len(quellen)}"),
    ]
    for z in zeilen:
        ue.append(z)
    ue["A1"].font = Font(bold=True, size=14)
    for r in range(2, len(zeilen) + 1):
        ue.cell(row=r, column=1).font = Font(bold=True)
    if alter is not None and alter > 1:
        ue["B3"].fill = WARN_FILL
        ue.append(("Achtung", "Die Daten sind älter als ein Tag. Im Repo unter "
                   "Actions den Lauf 'Arbeitgeber sammeln' prüfen."))
        ue.cell(row=ue.max_row, column=1).font = Font(bold=True)
    ue.append(())
    ue.append(("Hinweise", "Blatt Stellen: grün = im letzten Lauf neu dazugekommen, "
               "orange = Quelle beim letzten Lauf nicht gelesen (Stand älter). "
               "Blatt Quellen: Status je Arbeitgeber."))

    st = wb.create_sheet("Stellen")
    _kopf(st, ["Arbeitgeber", "Stelle", "Ort", "Veröffentlicht",
               "Erstmals gesehen", "Zuletzt gesehen", "Quelle gelesen", "Link"],
          [34, 60, 30, 14, 16, 16, 14, 60])
    for s in sorted(stellen, key=lambda s: ((s.get("sourceLabel") or "").lower(),
                                            (s.get("title") or "").lower())):
        gelesen = status.get(s.get("source")) == "done"
        st.append([s.get("sourceLabel") or s.get("company"), s.get("title"),
                   s.get("location") or None, _datum(s.get("posted")),
                   _datum(s.get("erstmalsGesehen")),
                   _datum(s.get("zuletztGesehen")),
                   "ja" if gelesen else "nein", s.get("url")])
        r = st.max_row
        for c in (4, 5, 6):
            st.cell(row=r, column=c).number_format = DATUM
        link = st.cell(row=r, column=8)
        if link.value:
            link.hyperlink = link.value
            link.font = Font(color="0563C1", underline="single")
        fill = (NEU_FILL if _datum(s.get("erstmalsGesehen")) == stand
                else None if gelesen else WARN_FILL)
        if fill:
            for c in range(1, 8):
                st.cell(row=r, column=c).fill = fill
    st.auto_filter.ref = f"A1:H{max(st.max_row, 1)}"

    qu = wb.create_sheet("Quellen")
    _kopf(qu, ["Arbeitgeber", "Status", "Stellen", "Letzter Erfolg", "Detail"],
          [34, 18, 10, 16, 80])
    for q in sorted(quellen, key=lambda q: (q.get("status") != "done",
                                            (q.get("label") or "").lower())):
        qu.append([q.get("label") or q.get("key"), q.get("status"),
                   q.get("anzahl"), _datum(q.get("letzterErfolg")),
                   q.get("detail")])
        qu.cell(row=qu.max_row, column=4).number_format = DATUM
        if q.get("status") != "done":
            qu.cell(row=qu.max_row, column=2).fill = WARN_FILL
    qu.auto_filter.ref = f"A1:E{max(qu.max_row, 1)}"

    if laeufe:
        letzter = max(r["lauf"] for r in laeufe)
        jetzt = [r for r in laeufe if r["lauf"] == letzter]
        leer = [r for r in jetzt if int(r["stellen_lauf"] or 0) == 0]
        offen = [r for r in leer if r["quelle"] not in ausnahmen]
        ue.insert_rows(8)
        ue.cell(row=8, column=1, value="Quellen ohne Stellen (letzter Lauf)").font = Font(bold=True)
        ue.cell(row=8, column=2, value=f"{len(leer)} von {len(jetzt)}, davon {len(offen)} zu prüfen "
                f"und {len(leer) - len(offen)} auf der Ausnahmeliste (Blätter Läufe, Ohne Ergebnis)")
        if offen:
            ue.cell(row=8, column=2).fill = WARN_FILL

        # --- Matrix Quelle x Lauf
        laufzeiten = sorted({r["lauf"] for r in laeufe})[-MAX_LAEUFE:]
        je = {}
        for r in laeufe:
            je.setdefault(r["quelle"], {})[r["lauf"]] = r
        def folge(rows_q):
            n = 0
            for lz in reversed(laufzeiten):
                r = rows_q.get(lz)
                if r is None or int(r["stellen_lauf"] or 0) != 0:
                    break
                n += 1
            return n
        def letzter_erfolg(rows_q):
            ok = [r["datum"] for r in rows_q.values() if int(r["stellen_lauf"] or 0) > 0]
            return _datum(max(ok)) if ok else None
        quellen_neu = {r["quelle"]: r for r in jetzt}
        reihen = sorted(quellen_neu, key=lambda k: (int(quellen_neu[k]["stellen_lauf"] or 0) > 0 or k in ausnahmen,
                                                    k in ausnahmen, quellen_neu[k]["label"].casefold()))
        lf = wb.create_sheet("Läufe")
        _kopf(lf, ["Arbeitgeber", "Adapter", "Status zuletzt", "Läufe ohne Ergebnis in Folge", "Letzter Erfolg"]
              + [lz[5:16].replace("T", " ") for lz in laufzeiten],
              [34, 16, 18, 14, 14] + [11] * len(laufzeiten))
        for k in reihen:
            r0, rq = quellen_neu[k], je[k]
            lf.append([r0["label"], r0["adapter"], r0["status"], folge(rq), letzter_erfolg(rq)]
                      + [int(rq[lz]["stellen_lauf"] or 0) if lz in rq else None for lz in laufzeiten])
            zr = lf.max_row
            lf.cell(row=zr, column=5).number_format = DATUM
            for j, lz in enumerate(laufzeiten, start=6):
                c = lf.cell(row=zr, column=j)
                if c.value == 0:
                    c.fill = GRAU_FILL if k in ausnahmen else FEHL_FILL
            if k in ausnahmen:
                lf.cell(row=zr, column=1).fill = GRAU_FILL
        lf.freeze_panes = "F2"
        lf.auto_filter.ref = f"A1:{get_column_letter(5 + len(laufzeiten))}{max(lf.max_row, 1)}"
        lf.cell(row=lf.max_row + 2, column=1, value=(
            "Zahl = in diesem Lauf gelesene Stellen. Rot = 0 Stellen (Fehler oder leer), grau = dauerhaft "
            "ohne Ergebnis erlaubt (ohne_stellen_ok.json). Leere Zelle = Quelle in diesem Lauf nicht abgefragt."))

        # --- Arbeitsliste: nur Quellen ohne Stellen im letzten Lauf
        oe = wb.create_sheet("Ohne Ergebnis")
        _kopf(oe, ["Arbeitgeber", "Schlüssel", "Adapter", "Status", "Detail", "Läufe in Folge",
                   "Letzter Erfolg", "Auf Ausnahmeliste", "Grund der Ausnahme"],
              [34, 22, 16, 18, 60, 14, 14, 16, 50])
        for r in sorted(leer, key=lambda r: (r["quelle"] in ausnahmen, r["label"].casefold())):
            oe.append([r["label"], r["quelle"], r["adapter"], r["status"], r["detail"] or None,
                       folge(je[r["quelle"]]), letzter_erfolg(je[r["quelle"]]),
                       "ja" if r["quelle"] in ausnahmen else "nein", ausnahmen.get(r["quelle"])])
            zr = oe.max_row
            oe.cell(row=zr, column=7).number_format = DATUM
            oe.cell(row=zr, column=2 if r["quelle"] in ausnahmen else 4).fill = (
                GRAU_FILL if r["quelle"] in ausnahmen else FEHL_FILL)
        oe.auto_filter.ref = f"A1:I{max(oe.max_row, 1)}"
    return wb


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    src = argv[0] if argv else "../stellen.json"
    out = argv[1] if len(argv) > 1 else "../stellen.xlsx"
    with open(src, encoding="utf-8") as fh:
        doc = json.load(fh)
    basis = os.path.dirname(os.path.abspath(src))
    laeufe, ausnahmen = [], {}
    try:
        with open(os.path.join(basis, "laeufe.csv"), encoding="utf-8", newline="") as fh:
            laeufe = list(csv.DictReader(fh))
    except OSError:
        pass
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ohne_stellen_ok.json"),
                  encoding="utf-8") as fh:
            ausnahmen = json.load(fh)
    except (OSError, ValueError):
        pass
    build(doc, laeufe=laeufe, ausnahmen=ausnahmen).save(out)
    print(f"Excel geschrieben: {out}")


if __name__ == "__main__":
    main()
