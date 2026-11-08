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


class DetailTest(unittest.TestCase):
    def test_detail_is_kept_for_failed_source(self):
        failed = {"label": "X", "status": "robots_unavailable", "jobs": [], "detail": "gone HTTP 404"}
        catalog = batch.merge(None, {"x": failed}, "2026-11-09", NOW)
        self.assertEqual(catalog["quellen"][0]["detail"], "gone HTTP 404")
        self.assertIn("gone HTTP 404", batch.overview(catalog))


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
        options = SimpleNamespace(max_jobs=60, max_details=25, documents=90, seconds=300, pause=0, strict_robots=False)
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


class CrawlerDetailTest(unittest.TestCase):
    def crawl_with(self, robots_error=None, robots_text=None, **extra):
        from safe_http import FetchError
        import crawler

        class Fake:
            def __init__(self, budget):
                self.budget, self.last = budget, {}

            def get(self, raw, hosts, authorize=None, **kw):
                if raw.endswith("/robots.txt"):
                    if robots_error:
                        raise robots_error
                    return raw, robots_text
                if authorize:
                    authorize(raw)
                return raw, "<html></html>"

        req = SimpleNamespace(q="", location="", radius_km=25, sources=["stihl"], **extra)
        self.fetched = []
        with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "stihl"}):
            return crawler.crawl(req, Fake)["sources"][0]

    def test_robots_404_reports_cause(self):
        from safe_http import FetchError
        report = self.crawl_with(robots_error=FetchError("gone", http_status=404))
        self.assertEqual((report["status"], report["detail"]), ("robots_unavailable", "gone HTTP 404"))

    def test_robots_blocked_reports_cause(self):
        from safe_http import FetchError
        report = self.crawl_with(robots_error=FetchError("blocked"))
        self.assertEqual((report["status"], report["detail"]), ("robots_unavailable", "blocked"))

    def test_robots_without_user_agent_reports_cause(self):
        report = self.crawl_with(robots_text="<html>Seite nicht gefunden</html>")
        self.assertEqual(report["status"], "robots_unavailable")
        self.assertIn("User-agent", report["detail"])

    def test_missing_robots_allowed_only_when_enabled(self):
        from safe_http import FetchError
        for status in (404, 410):
            error = FetchError("gone", http_status=status)
            strict = self.crawl_with(robots_error=error)
            self.assertEqual(strict["status"], "robots_unavailable")
            lenient = self.crawl_with(robots_error=error, robots_missing_ok=True)
            self.assertNotEqual(lenient["status"], "robots_unavailable")

    def test_lenient_mode_still_stops_on_other_robots_failures(self):
        from safe_http import FetchError
        for error in (FetchError("blocked"), FetchError("upstream_error", http_status=503),
                      FetchError("timeout"), FetchError("network_error")):
            report = self.crawl_with(robots_error=error, robots_missing_ok=True)
            self.assertEqual(report["status"], "robots_unavailable", error.code)

    def test_lenient_mode_still_obeys_disallow(self):
        report = self.crawl_with(robots_text="User-agent: *\nDisallow: /", robots_missing_ok=True)
        self.assertEqual(report["status"], "robots_denied")


class DiagnosticDetailTest(unittest.TestCase):
    def test_unsafe_target_and_unsupported_carry_reasons(self):
        from safe_http import FetchError, target

        def dns_down(*a, **k):
            raise OSError("no dns")

        with self.assertRaises(FetchError) as caught:
            target("https://a.example/", ("a.example",), dns_down)
        self.assertIn("DNS OSError a.example", caught.exception.detail)

        private = lambda *a, **k: [(0, 0, 0, "", ("10.0.0.5", 443))]
        with self.assertRaises(FetchError) as caught:
            target("https://a.example/", ("a.example",), private)
        self.assertIn("10.0.0.5", caught.exception.detail)

    def test_robots_snippet_is_reported(self):
        report = CrawlerDetailTest.crawl_with(CrawlerDetailTest(), robots_text="<html>\n  Seite   nicht gefunden </html>")
        self.assertIn("Seite nicht gefunden", report["detail"])


class RobotsVariantsTest(CrawlerDetailTest):
    def test_bom_robots_with_empty_disallow_is_parsed_even_when_strict(self):
        report = self.crawl_with(robots_text="﻿User-agent: *\nDisallow:")
        self.assertNotEqual(report["status"], "robots_unavailable")

    def test_html_instead_of_robots_counts_as_missing_only_when_lenient(self):
        page = "<!DOCTYPE html><html><head><title>App</title></head></html>"
        self.assertEqual(self.crawl_with(robots_text=page)["status"], "robots_unavailable")
        self.assertNotEqual(self.crawl_with(robots_text=page, robots_missing_ok=True)["status"], "robots_unavailable")

    def test_sitemap_only_file_counts_as_no_rules_only_when_lenient(self):
        text = "Sitemap: https://example.de/sitemap.xml"
        self.assertEqual(self.crawl_with(robots_text=text)["status"], "robots_unavailable")
        self.assertNotEqual(self.crawl_with(robots_text=text, robots_missing_ok=True)["status"], "robots_unavailable")

    def test_block_pages_never_count_as_missing(self):
        for page in ("<html>Just a moment...</html>", "<html>Access Denied</html>", "<html>Please solve the CAPTCHA</html>"):
            report = self.crawl_with(robots_text=page, robots_missing_ok=True)
            self.assertEqual(report["status"], "robots_unavailable", page)


class TransportEncodingTest(unittest.TestCase):
    def fetch(self, body, headers, robots=False):
        import gzip as gz
        from safe_http import Budget, Transport

        class Response:
            status = 200

            def __init__(self):
                self.data = body

            def getheader(self, name, default=None):
                return headers.get(name, default)

            def read(self, n=-1):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

        class Connection:
            def __init__(self, *a): pass
            def request(self, *a, **k): pass
            def getresponse(self): return Response()
            def close(self): pass

        transport = Transport(Budget(), resolve=lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))], connection=Connection)
        return transport.get("https://a.example/robots.txt" if robots else "https://a.example/", ("a.example",), robots_request=robots)[1]

    def test_gzip_is_decoded_even_though_identity_was_requested(self):
        import gzip as gz
        text = self.fetch(gz.compress(b"User-agent: *\nDisallow:"), {"Content-Encoding": "gzip", "Content-Type": "text/plain"}, robots=True)
        self.assertIn("User-agent", text)

    def test_gzip_bomb_is_rejected(self):
        import gzip as gz
        from safe_http import FetchError
        with self.assertRaises(FetchError) as caught:
            self.fetch(gz.compress(b"a" * (3 * 1024 * 1024)), {"Content-Encoding": "gzip", "Content-Type": "text/html"})
        self.assertEqual(caught.exception.code, "too_large")

    def test_other_encodings_stay_rejected(self):
        from safe_http import FetchError
        with self.assertRaises(FetchError) as caught:
            self.fetch(b"x", {"Content-Encoding": "br", "Content-Type": "text/html"})
        self.assertEqual(caught.exception.code, "unsupported")

    def test_text_txt_is_accepted_for_robots_only(self):
        from safe_http import FetchError
        self.assertIn("Disallow", self.fetch(b"User-agent: *\nDisallow: /x", {"Content-Type": "text/txt;charset=utf-8"}, robots=True))
        with self.assertRaises(FetchError):
            self.fetch(b"hallo", {"Content-Type": "text/txt"})
