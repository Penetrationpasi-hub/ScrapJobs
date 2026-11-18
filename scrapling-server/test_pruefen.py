import json
import unittest
from pathlib import Path

import pruefen
from sources import registry


def zeile(lauf, quelle, status="done", n=3, label=None):
    return {"lauf": lauf, "datum": lauf[:10], "quelle": quelle, "label": label or quelle, "adapter": "html",
            "status": status, "stellen_lauf": str(n), "neu": "0", "im_katalog": str(n), "detail": ""}


class PruefenTest(unittest.TestCase):
    def test_nur_juengster_lauf_und_ausnahmen(self):
        rows = [zeile("2026-11-17T10:00:00", "a", "timeout", 0), zeile("2026-11-17T10:00:00", "b"),
                zeile("2026-11-18T10:00:00", "a"), zeile("2026-11-18T10:00:00", "b", "network_error", 0),
                zeile("2026-11-18T10:00:00", "c", "unsupported", 0), zeile("2026-11-18T10:00:00", "d")]
        fehler, entbehrlich, lauf = pruefen.pruefe(rows, {"c": "x", "d": "x"})
        self.assertEqual([r["quelle"] for r in fehler], ["b"])
        self.assertEqual([r["quelle"] for r in entbehrlich], ["d"])
        self.assertEqual(lauf, "2026-11-18T10:00:00")

    def test_done_ohne_stellen_ist_fehler(self):
        fehler, _, _ = pruefen.pruefe([zeile("2026-11-18T10:00:00", "a", "done", 0)], {})
        self.assertEqual(len(fehler), 1)

    def test_laeufe_in_folge(self):
        rows = [zeile("2026-11-16T1", "a"), zeile("2026-11-17T1", "a", "timeout", 0), zeile("2026-11-18T1", "a", "timeout", 0)]
        self.assertEqual(pruefen.seit(rows, "a"), 2)

    def test_ausnahmeliste_nennt_nur_bekannte_quellen(self):
        ausnahmen = json.loads(Path(__file__).with_name("ohne_stellen_ok.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(set(ausnahmen) - set(registry())), [])


if __name__ == "__main__":
    unittest.main()
