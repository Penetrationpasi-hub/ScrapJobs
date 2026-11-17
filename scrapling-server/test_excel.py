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


if __name__ == "__main__":
    unittest.main()
