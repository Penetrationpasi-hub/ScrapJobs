import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from extraction import canonical, discovery, extract
from safe_http import Budget, FetchError, PinnedHTTPS, Transport, target
from sources import BOARDS, EMPLOYERS, Source
from crawler import crawl
import main
from fastapi.testclient import TestClient


def fixture(source, multiple=False, **changes):
    url = ("https://de.indeed.com/viewjob?jk=abc" if source.key == "indeed" else
           "https://www.stepstone.de/stellenangebote--Software--123-inline.html" if source.key == "stepstone" else
           "https://jobs.festo.com/job/software-entwickler-c" if source.key == "festo" else
           "https://jobs.smartrecruiters.com/BoschGroup/123-software")
    posting = {"@type": "JobPosting", "url": url, "title": "Software Entwickler C# (m/w/d)",
               "hiringOrganization": {"name": "Beispiel GmbH"},
               "jobLocation": {"address": {"addressLocality": "Waiblingen", "addressCountry": "DE"}},
               "description": "<p>C# und schöne Büros</p><script>bad()</script>",
               "datePosted": "2026-10-30", "validThrough": "2099-01-01"}
    posting.update(changes)
    data = [posting, posting] if multiple else posting
    return url, '<script type="application/ld+json">' + json.dumps(data).replace("</", "<\\/") + "</script>"


class Extraction(unittest.TestCase):
    def test_all_adapters_accept_actual_posting(self):
        for source in (*BOARDS, *EMPLOYERS):
            url, html = fixture(source)
            job = extract(html, url, source, "Software", datetime(2026, 11, 1, tzinfo=timezone.utc))
            self.assertEqual(job["title"], "Software Entwickler C# (m/w/d)")
            self.assertEqual(job["company"], "Beispiel GmbH")
            self.assertNotIn("bad()", job["description"])
            self.assertIn("Scrapling", job["source"])

    def test_reject_lists_even_with_matching_title(self):
        for source in (*BOARDS, *EMPLOYERS):
            url, html = fixture(source)
            for index in (source.start("Software", "Berlin"), "https://jobs.festo.com/careers/jobs"):
                self.assertIsNone(extract(html, index, source))
            self.assertIsNone(extract(fixture(source, multiple=True)[1], url, source))

    def test_missing_expired_mismatch_and_placeholders(self):
        source = EMPLOYERS[0]
        for changes in ({"hiringOrganization": {}}, {"hiringOrganization": {"name": "verschiedene Arbeitgeber"}},
                        {"title": ""}, {"validThrough": "2020-01-01"}, {"validThrough": "nonsense"},
                        {"url": "https://jobs.festo.com/job/invented-42"}):
            url, html = fixture(source, **changes)
            self.assertIsNone(extract(html, url, source))
        url, html = fixture(source)
        self.assertIsNone(extract(html, url, source, "Tischler"))
        self.assertIsNone(extract("<h1>Software Entwickler – Beispiel GmbH</h1>", url, source))
        self.assertIsNone(extract(html + "<p>Diese Stelle ist bereits besetzt</p>", url, source))

    def test_actual_dom_evidence_and_no_slug_token_requirement(self):
        source = BOARDS[0]
        url, _ = fixture(source)
        html = '<h1 class="jobsearch-JobInfoHeader-title">C# Entwickler</h1><div data-testid="inlineHeader-companyName"><a>Firma GmbH</a></div>'
        job = extract(html, url, source, "C#")
        self.assertEqual(job["title"], "C# Entwickler")
        self.assertEqual(job["location"], "")
        self.assertIsNone(extract(html.replace("Firma GmbH", ""), url, source))

    def test_discovery_and_canonical_dedup(self):
        source = EMPLOYERS[0]
        url, _ = fixture(source)
        html = f'<a href="{url}?utm_source=x">x</a><a href="{url}#more">y</a><a href="https://evil.test/job/1">bad</a><a rel="next" href="?page=2">Next</a>'
        links, next_page = discovery(html, "https://jobs.festo.com/search/", source)
        self.assertEqual(links, [url])
        self.assertIn("page=2", next_page)
        self.assertNotEqual(canonical(url + "?jobId=1"), canonical(url + "?jobId=2"))


class Network(unittest.TestCase):
    @staticmethod
    def resolve(ip):
        return lambda *args, **kwargs: [(2, 1, 6, "", (ip, 443))]

    def test_private_mapped_and_reserved(self):
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1", "192.0.2.1", "224.0.0.1", "ff02::1", "2002:7f00:1::"):
            with self.assertRaises(FetchError):
                target("https://jobs.festo.com/job/x", ("jobs.festo.com",), self.resolve(ip))
        for url in ("http://jobs.festo.com/x", "https://user:pass@jobs.festo.com/x", "https://jobs.festo.com.evil.test/x",
                    "https://jobs.festo.com:8443/x"):
            with self.assertRaises(FetchError):
                target(url, ("jobs.festo.com",), self.resolve("8.8.8.8"))

    def test_socket_is_pinned_without_second_resolution(self):
        connection = PinnedHTTPS("jobs.festo.com", "8.8.8.8", 1)
        with patch("safe_http.socket.socket") as socket_mock:
            socket_mock.return_value = sock = unittest.mock.Mock()
            connection._context = ctx = unittest.mock.Mock()
            connection.connect()
            sock.connect.assert_called_once_with(("8.8.8.8", 443))
            ctx.wrap_socket.assert_called_once_with(sock, server_hostname="jobs.festo.com")

    def test_redirect_revalidates_and_counts(self):
        calls = []
        class Connection:
            def __init__(self, host, address, timeout): calls.append(address)
            def request(self, *args, **kwargs): pass
            def close(self): pass
            def getresponse(self):
                return type("Response", (), {"status": 302, "getheader": lambda _, key, default=None: "https://private.test/job/1"})()
        transport = Transport(Budget(), self.resolve("8.8.8.8"), Connection)
        with self.assertRaises(FetchError):
            transport.get("https://jobs.festo.com/job/1", ("jobs.festo.com",))
        self.assertEqual(calls, ["8.8.8.8"])
        self.assertEqual(transport.budget.remaining, 38)
        answers = iter(["8.8.8.8", "127.0.0.1"])
        resolver = lambda *args, **kwargs: [(2, 1, 6, "", (next(answers), 443))]
        class Rebinding(Connection):
            def getresponse(self):
                return type("Response", (), {"status": 302, "getheader": lambda _, key, default=None: "https://jobs.festo.com/job/2"})()
        with self.assertRaisesRegex(FetchError, "unsafe_target"):
            Transport(Budget(), resolver, Rebinding).get("https://jobs.festo.com/job/1", ("jobs.festo.com",))

    def test_budget_deadline_and_size(self):
        budget = Budget(documents=1)
        budget.claim()
        with self.assertRaises(FetchError): budget.claim()
        with self.assertRaises(FetchError): Budget(seconds=0).claim()
        class Connection:
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def close(self): pass
            def getresponse(self):
                return type("Response", (), {"status": 200, "getheader": lambda _, key, default=None: "text/html" if key == "Content-Type" else default,
                                             "read": lambda _, size: b"x" * size})()
        with self.assertRaisesRegex(FetchError, "too_large"):
            Transport(Budget(), self.resolve("8.8.8.8"), Connection).get("https://jobs.festo.com/job/x", ("jobs.festo.com",))


class Crawling(unittest.TestCase):
    def request(self, sources=("festo",)):
        return main.Search(q="Software", location="Waiblingen", radius_km=25, sources=list(sources), id="a" * 64)

    def test_live_sources_default_off(self):
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": ""}):
            result = crawl(self.request())
        self.assertEqual(result["documents"], 0)
        self.assertEqual(result["sources"][0]["status"], "not_approved")

    def test_robots_two_pages_filters_and_limits(self):
        source = EMPLOYERS[0]
        url, html = fixture(source)
        seen = []
        class FakeTransport:
            def __init__(self, budget): self.budget, self.last = budget, {}
            def get(self, raw, hosts, authorize=None):
                if authorize: authorize(raw)
                self.budget.claim(); seen.append(raw)
                if raw.endswith("robots.txt"): return raw, "User-agent: *\nAllow: /\n"
                if "/search/" in raw: return raw, f'<a href="{url}">Software</a><a rel="next" href="?page=2">next</a>'
                return raw, html
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "festo"}):
            result = crawl(self.request(), FakeTransport)
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(len(seen), 4)  # robots + 2 discovery + detail
        self.assertEqual(result["sources"][0]["status"], "done")

    def test_blockade_and_robots_not_reported_as_no_jobs(self):
        for code in ("blocked", "timeout", "robots_denied"):
            class Fake:
                def __init__(self, budget): self.last, self.budget = {}, budget
                def get(self, *args, **kwargs): raise FetchError(code)
            with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "festo"}):
                result = crawl(self.request(), Fake)
            self.assertNotEqual(result["sources"][0]["status"], "done")


class API(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.env = patch.dict(os.environ, {"SCRAPLING_ENABLED": "1", "SCRAPLING_API_TOKEN": "test-only"})
        self.env.start()
        self.headers = {"Authorization": "Bearer test-only"}
        main.searches.clear()

    def tearDown(self): self.env.stop()

    def test_auth_disable_and_no_network_health(self):
        self.assertEqual(self.client.get("/health").json()["browser"], False)
        self.assertEqual(self.client.get("/sources").status_code, 401)
        self.assertEqual(self.client.get("/sources", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post("/search", content="x" * 5000, headers=self.headers).status_code, 413)
        self.assertEqual(self.client.post("/search", content="not-json").status_code, 401)
        with patch.dict(os.environ, {"SCRAPLING_ENABLED": "0"}):
            self.assertEqual(self.client.get("/sources", headers=self.headers).status_code, 503)

    def test_start_idempotency_invalid_input_restart_and_capacity(self):
        req = Crawling().request().model_dump()
        with patch.object(main.pool, "submit") as submit:
            self.assertEqual(self.client.post("/search", json=req, headers=self.headers).status_code, 200)
            self.assertEqual(self.client.post("/search", json=req, headers=self.headers).status_code, 200)
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(self.client.post("/search", json={**req, "q": "Other"}, headers=self.headers).status_code, 409)
            self.assertEqual(self.client.post("/search", json={**req, "id": "b" * 64}, headers=self.headers).status_code, 429)
        self.assertEqual(self.client.post("/search", json={**req, "sources": ["https://evil.test"]}, headers=self.headers).status_code, 422)
        main.searches.clear()
        self.assertEqual(self.client.get("/search/" + req["id"], headers=self.headers).status_code, 404)
        main.searches[req["id"]] = {"status": "running", "started": time.time() - main.RUN_SECONDS - 10}
        self.assertEqual(self.client.get("/search/" + req["id"], headers=self.headers).json()["status"], "error")

    def test_real_supervisor_finishes_without_live_approval(self):
        req = Crawling().request()
        main.searches[req.id] = {"status": "running", "started": time.time()}
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": ""}):
            main.finish(req)
        result = main.searches[req.id]
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["documents"], 0)

    def test_hard_deadline_terminates_child(self):
        req = Crawling().request()
        main.searches[req.id] = {"status": "running", "started": time.time()}
        with patch.object(main.multiprocessing, "get_context") as context:
            output = context.return_value.Queue.return_value
            output.get.side_effect = main.queue.Empty
            process = context.return_value.Process.return_value
            process.is_alive.return_value = True
            main.finish(req)
            output.get.assert_called_once_with(timeout=main.RUN_SECONDS)
            process.terminate.assert_called_once()
        self.assertEqual(main.searches[req.id]["error"], "timeout")


if __name__ == "__main__":
    unittest.main()
