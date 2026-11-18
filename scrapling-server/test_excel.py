import unittest
from datetime import date

import excel

DOC = {
    "aktualisiert": "2026-11-17T06:40:00+00:00",
    "quellen": [
        {"key": "a", "label": "Firma A", "status": "done", "letzterErfolg": "2026-11-17", "anzahl": 2},
        {"key": "b", "label": "Firma B", "status": "timeout", "letzterErfolg": "2026-11-10", "anzahl": 1},
    ],
    "stellen": [
        {"title": "Neu", "url": "https://a.example/1", "source": "a", "sourceLabel": "Firma A",
         "erstmalsGesehen": "2026-11-17", "zuletztGesehen": "2026-11-17"},
        {"title": "Alt", "url": "https://a.example/2", "source": "a", "sourceLabel": "Firma A",
         "erstmalsGesehen": "2026-11-12", "zuletztGesehen": "2026-11-17"},
        {"title": "Stehen geblieben", "url": "https://b.example/1", "source": "b", "sourceLabel": "Firma B",
         "erstmalsGesehen": "2026-11-09", "zuletztGesehen": "2026-11-10"},
    ],
}


class ExcelTest(unittest.TestCase):
    def test_blaetter_und_inhalt(self):
        wb = excel.build(DOC, heute=date(2026, 11, 17))
        self.assertEqual(wb.sheetnames, ["Übersicht", "Stellen", "Quellen"])
        ue = {r[0]: r[1] for r in wb["Übersicht"].iter_rows(values_only=True) if r and r[0]}
        self.assertEqual(ue["Stellen"], 3)
        self.assertEqual(ue["davon neu im letzten Lauf"], 1)
        self.assertEqual(ue["Quellen gelesen"], "1 von 2")
        self.assertNotIn("Achtung", ue)
        st = list(wb["Stellen"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(st), 3)
        self.assertEqual([r[6] for r in st].count("nein"), 1)

    def test_warnung_bei_alten_daten(self):
        wb = excel.build(DOC, heute=date(2026, 11, 20))
        ue = {r[0]: r[1] for r in wb["Übersicht"].iter_rows(values_only=True) if r and r[0]}
        self.assertIn("Achtung", ue)
        self.assertEqual(ue["Alter der Daten"], "3 Tage")


LAEUFE = [
    {"lauf": "2026-11-17T10:00:00", "datum": "2026-11-17", "quelle": "a", "label": "Firma A", "adapter": "html",
     "status": "done", "stellen_lauf": "2", "neu": "0", "im_katalog": "2", "detail": ""},
    {"lauf": "2026-11-17T10:00:00", "datum": "2026-11-17", "quelle": "b", "label": "Firma B", "adapter": "sitemap",
     "status": "done", "stellen_lauf": "1", "neu": "0", "im_katalog": "1", "detail": ""},
    {"lauf": "2026-11-18T10:00:00", "datum": "2026-11-18", "quelle": "a", "label": "Firma A", "adapter": "html",
     "status": "done", "stellen_lauf": "3", "neu": "1", "im_katalog": "3", "detail": ""},
    {"lauf": "2026-11-18T10:00:00", "datum": "2026-11-18", "quelle": "b", "label": "Firma B", "adapter": "sitemap",
     "status": "timeout", "stellen_lauf": "0", "neu": "0", "im_katalog": "1", "detail": "TimeoutError b.example"},
    {"lauf": "2026-11-18T10:00:00", "datum": "2026-11-18", "quelle": "c", "label": "Firma C", "adapter": "html",
     "status": "unsupported", "stellen_lauf": "0", "neu": "0", "im_katalog": "0", "detail": ""},
]


class LaeufeBlattTest(unittest.TestCase):
    def test_blaetter_matrix_und_arbeitsliste(self):
        wb = excel.build(DOC, heute=date(2026, 11, 18), laeufe=LAEUFE, ausnahmen={"c": "kein Adapter"})
        self.assertEqual(wb.sheetnames, ["Übersicht", "Stellen", "Quellen", "Läufe", "Ohne Ergebnis"])
        lf = list(wb["Läufe"].iter_rows(min_row=2, max_row=4, values_only=True))
        self.assertEqual(lf[0][0], "Firma B")                 # Problemfall zuerst
        self.assertEqual((lf[0][3], lf[0][4].isoformat()), (1, "2026-11-17"))
        self.assertEqual(list(lf[0][5:7]), [1, 0])
        self.assertEqual(lf[2][0], "Firma C")                 # Ausnahme ganz unten
        oe = list(wb["Ohne Ergebnis"].iter_rows(min_row=2, values_only=True))
        self.assertEqual([(r[0], r[7]) for r in oe], [("Firma B", "nein"), ("Firma C", "ja")])
        ue = {r[0]: r[1] for r in wb["Übersicht"].iter_rows(values_only=True) if r and r[0]}
        self.assertIn("2 von 3, davon 1 zu prüfen und 1 auf der Ausnahmeliste", ue["Quellen ohne Stellen (letzter Lauf)"])


if __name__ == "__main__":
    unittest.main()
