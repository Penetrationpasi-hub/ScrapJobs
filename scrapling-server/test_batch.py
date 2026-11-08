import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import batch
from sources import registry

NOW = datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)


def job(n, company="ACME GmbH"):
    return {"id": f"scrapling-{n}", "title": f"Stelle {n}", "company": company, "location": "Waiblingen",
            "url": f"https://example.de/job/{n}", "posted": "2026-11-01", "source": "ACME · Scrapling",
            "salary": None, "description": "Volltext darf nicht veröffentlicht werden"}


def result(status, *jobs):
    return {"label": "ACME", "status": status, "jobs": list(jobs)}


class MergeTest(unittest.TestCase):
    def test_new_job_keeps_metadata_only(self):
        catalog = batch.merge(None, {"acme": result("done", job(1))}, "2026-11-09", NOW)
        row = catalog["stellen"][0]
        self.assertNotIn("description", row)
        self.assertNotIn("salary", row)
        self.assertEqual((row["erstmalsGesehen"], row["zuletztGesehen"]), ("2026-11-09", "2026-11-09"))
        self.assertEqual(catalog["quellen"][0]["anzahl"], 1)
        self.assertEqual(catalog["aktualisiert"], "2026-11-09T04:00:00+00:00")

    def test_first_seen_survives_and_last_seen_moves(self):
        first = batch.merge(None, {"acme": result("done", job(1))}, "2026-11-09", NOW)
        second = batch.merge(first, {"acme": result("done", job(1))}, "2026-11-10", NOW)
        row = second["stellen"][0]
        self.assertEqual((row["erstmalsGesehen"], row["zuletztGesehen"]), ("2026-11-09", "2026-11-10"))

    def test_vanished_job_stays_only_for_grace_period(self):
        first = batch.merge(None, {"acme": result("done", job(1), job(2))}, "2026-11-09", NOW)
        day3 = batch.merge(first, {"acme": result("done", job(1))}, "2026-11-12", NOW)
        self.assertEqual(len(day3["stellen"]), 2)
        day4 = batch.merge(day3, {"acme": result("done", job(1))}, "2026-11-13", NOW)
        self.assertEqual([r["id"] for r in day4["stellen"]], ["scrapling-1"])

    def test_failed_source_keeps_previous_state(self):
        first = batch.merge(None, {"acme": result("done", job(1))}, "2026-11-09", NOW)
        for status in ("timeout", "robots_denied", "unsupported", "worker_error", "no_verified_jobs"):
            later = batch.merge(first, {"acme": result(status)}, "2026-12-24", NOW)
            self.assertEqual(later["stellen"], first["stellen"], status)
            self.assertEqual(later["quellen"][0]["letzterErfolg"], "2026-11-09")
            self.assertEqual(later["quellen"][0]["status"], status)

    def test_sources_are_independent(self):
        first = batch.merge(None, {"a": result("done", job(1)), "b": result("done", job(2, "B AG"))}, "2026-11-09", NOW)
        later = batch.merge(first, {"a": result("timeout"), "b": result("done", job(2, "B AG"))}, "2026-11-20", NOW)
        self.assertEqual({r["id"] for r in later["stellen"]}, {"scrapling-1", "scrapling-2"})


class OverviewTest(unittest.TestCase):
    def test_markdown_groups_by_company_and_lists_sources(self):
        catalog = batch.merge(None, {"acme": result("done", job(1), job(2, "B AG")), "kaputt": result("timeout")}, "2026-11-09", NOW)
        text = batch.overview(catalog)
        self.assertIn("2 Stellen aus 1 von 2 Quellen", text)
        self.assertIn("### ACME GmbH", text)
        self.assertIn("[Stelle 1](https://example.de/job/1)", text)
        self.assertIn("| ACME | done | 2 |", text)
        self.assertIn("| ACME | timeout | 0 | – |", text)


class SelectionTest(unittest.TestCase):
    def test_default_excludes_boards_and_unavailable(self):
        keys = batch.select_sources(registry())
        for key in ("indeed", "stepstone", "bluum_bw", "jobsuche_bw", "signalhorn", "bkz"):
            self.assertNotIn(key, keys)
        self.assertIn("stihl", keys)
        self.assertGreater(len(keys), 50)

    def test_isolated_boards_run_last(self):
        keys = batch.select_sources(registry())
        tail = keys[-2:]
        self.assertEqual(set(tail), {"rems_murr_jobs", "zvw"})

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            batch.select_sources(registry(), only=["gibtsnicht"])


class CollectTest(unittest.TestCase):
    def test_crawl_runs_per_source_with_catalog_request(self):
        seen = []

        def fake(req, factory):
            seen.append(req)
            if req.sources[0] == "boom":
                raise RuntimeError("x")
            return {"jobs": [job(1)], "sources": [{"status": "done"}]}

        configured = {"stihl": SimpleNamespace(label="STIHL"), "boom": SimpleNamespace(label="Boom")}
        options = SimpleNamespace(max_jobs=60, max_details=25, documents=90, seconds=300, pause=0)
        with mock.patch.object(batch, "crawl", fake):
            out = batch.collect(["stihl", "boom"], configured, options, factory=object(), sleep=lambda s: None, log=lambda m: None)
        self.assertEqual((out["stihl"]["status"], len(out["stihl"]["jobs"])), ("done", 1))
        self.assertEqual(out["boom"]["status"], "worker_error")
        self.assertTrue(all(r.q == "" and r.location == "" for r in seen))
        self.assertEqual(seen[0].max_details, 25)

    def test_shared_transport_spacing_across_sources(self):
        factory = batch.make_transport_factory()
        a, b = factory(SimpleNamespace()), factory(SimpleNamespace())
        a.last["host"] = 5
        self.assertEqual(b.last["host"], 5)


class MainTest(unittest.TestCase):
    def test_no_successful_source_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder, "stellen.json")
            out.write_text('{"alt": true}', encoding="utf-8")
            with mock.patch.object(batch, "collect", lambda *a, **k: {"stihl": result("timeout")}):
                self.assertEqual(batch.main(["--out", str(out), "--sources", "stihl"]), 1)
            self.assertEqual(out.read_text(encoding="utf-8"), '{"alt": true}')

    def test_writes_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder, "stellen.json")
            with mock.patch.object(batch, "collect", lambda *a, **k: {"stihl": result("done", job(1))}):
                self.assertEqual(batch.main(["--out", str(out), "--sources", "stihl"]), 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], 1)
            self.assertEqual(len(data["stellen"]), 1)
            self.assertEqual(os.environ["SCRAPLING_APPROVED_SOURCES"], "stihl")


if __name__ == "__main__":
    unittest.main()
