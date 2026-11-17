"""stellen.json -> stellen.xlsx: aktueller Stand zum schnellen Pruefen.

    python excel.py ../stellen.json ../stellen.xlsx

Blaetter: Uebersicht (Stand, Frische, Zahlen), Stellen (alle, mit Filter
und Link), Quellen (Status je Arbeitgeber). Alle Werte fest eingetragen,
keine Formeln, damit auch Vorschau-Apps am Handy alles anzeigen.
"""

import json
import sys
from datetime import date, datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

KOPF_FONT = Font(bold=True, color="FFFFFF")
KOPF_FILL = PatternFill("solid", start_color="1D3C6E")
WARN_FILL = PatternFill("solid", start_color="FCE4D6")
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


def build(doc, heute=None):
    heute = heute or datetime.now(timezone.utc).date()
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
    return wb


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    src = argv[0] if argv else "../stellen.json"
    out = argv[1] if len(argv) > 1 else "../stellen.xlsx"
    with open(src, encoding="utf-8") as fh:
        doc = json.load(fh)
    build(doc).save(out)
    print(f"Excel geschrieben: {out}")


if __name__ == "__main__":
    main()
