"""Reduced observed B-ite shapes; no network calls or private credentials."""
import copy
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bite_adapter import API, CONFIG, DETAIL, EMPLOYER, LISTING, TENANT, bite
from crawler import crawl
from safe_http import Budget, FetchError, Transport
from sources import registry


ID = "afc4b4a915d745df288481490d4a878c2b597e66"
NAME = "Klinikum Schloß Winnenden"
TITLE = "IT-Systemadministrator (w/m/d) mit Schwerpunkt Digitalisierung Kliniksysteme in Vollzeit"
SHELL = ('<script src="https://static.b-ite.com/jobs-api/loader-v1/api-loader-v1.min.js"></script>'
         '<div data-bite-jobs-api-listing="' + TENANT + '"></div>')
# Deliberately synthetic, public-client identity. No real identifier is saved.
SCRIPT = 'var client=o.createClient({key:"' + "a" * 40 + '"});'


def listing(ident=ID):
    return {"id": ident, "rootHash": ident, "title": TITLE, "url": DETAIL + ident + "0",
            "employer": {"uuid": EMPLOYER, "name": NAME},
            "startsOn": "2020-01-01T00:00:00+00:00", "endsOn": "2099-12-31T00:00:00+00:00"}


def posting(ident=ID):
    return {"@type": "JobPosting", "identifier": {"value": ident}, "title": TITLE,
            "hiringOrganization": {"name": NAME, "identifier": {"value": EMPLOYER}},
            "description": "Betreuung und Weiterentwicklung der Kliniksysteme in der zentralen IT-Abteilung.",
            "jobLocation": {"address": {"postalCode": "71364", "addressLocality": "Winnenden",
                                       "addressCountry": "de"}},
            "datePosted": "2020-01-01", "validThrough": "2099-12-31T00:00:00+00:00"}


def document(rows):
    return "".join('<script type="application/ld+json">' + json.dumps(row) + "</script>" for row in rows)


class BiteTests(unittest.TestCase):
    def setUp(self):
        self.source = registry()["zfp_winnenden"]
        self.rows = [listing()]
        self.posts = [posting()]
        self.shell, self.script = SHELL, SCRIPT
        self.calls = []
        self.final_override = None

    def get(self, raw, source, **options):
        self.calls.append((raw, options))
        if raw == LISTING:
            return raw, self.shell
        if raw == CONFIG:
            self.assertEqual(options, {"accept_javascript": True})
            return raw, self.script
        if raw == API:
            self.assertTrue(options["accept_json"])
            payload = options["json_body"]
            self.assertEqual(payload["channel"], 0)
            self.assertEqual(payload["origin"], LISTING)
            self.assertEqual(payload["key"], "a" * 40)
            return raw, json.dumps({"jobPostings": self.rows, "page": {"offset": 0, "total": len(self.rows)}})
        self.assertIn(raw, [row["url"] for row in self.rows])
        return self.final_override or raw, document(self.posts)

    def run_reader(self, query="Digitalisierung"):
        self.report = {"filtered": 0}
        return list(bite(self.source, SimpleNamespace(q=query), self.get, self.report))

    def test_concrete_job_not_apply_url(self):
        jobs = self.run_reader()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], NAME)
        self.assertIn("Winnenden", jobs[0]["location"])
        self.assertEqual(jobs[0]["url"], DETAIL + ID + "0")
        self.assertFalse(any("/apply" in url for url, _ in self.calls))
        self.assertEqual(len(self.calls), 4)

    def test_official_tenant_and_loader_required(self):
        for shell in [SHELL.replace(TENANT, "other-employer:main-listing"),
                      SHELL.replace("static.b-ite.com", "other.test")]:
            with self.subTest(shell=shell):
                self.shell, self.calls = shell, []
                with self.assertRaises(FetchError):
                    self.run_reader()
                self.assertEqual(len(self.calls), 1)

    def test_client_config_not_executed_or_guessed(self):
        for script in ["createSomethingElse()", SCRIPT + SCRIPT]:
            with self.subTest(script=script):
                self.script, self.calls = script, []
                with self.assertRaises(FetchError):
                    self.run_reader()
                self.assertFalse(any(url == API for url, _ in self.calls))

    def test_foreign_employer_id_url_and_expiry_rejected_before_fetch(self):
        bad_rows = []
        for field, value in [("employer", {"uuid": "foreign", "name": NAME}),
                             ("employer", {"uuid": EMPLOYER, "name": "Other Clinic"}),
                             ("rootHash", "b" * 40), ("id", "../../apply"),
                             ("url", DETAIL + ID + "0/apply"),
                             ("url", "https://127.0.0.1/jobposting/" + ID + "0"),
                             ("startsOn", "2099-01-01T00:00:00Z"),
                             ("endsOn", "2020-01-01T00:00:00Z"),
                             ("endsOn", "invalid")]:
            row = listing()
            row[field] = value
            bad_rows.append(row)
        for row in bad_rows:
            with self.subTest(row=row):
                self.rows, self.calls = [row], []
                self.assertEqual(self.run_reader(), [])
                self.assertEqual(len(self.calls), 3)

    def test_detail_must_confirm_exact_job_and_employer(self):
        bad = []
        for field, value in [("identifier", {"value": "b" * 40}),
                             ("hiringOrganization", {"name": NAME, "identifier": {"value": "foreign"}}),
                             ("hiringOrganization", {"name": "Another Employer", "identifier": {"value": EMPLOYER}}),
                             ("title", "Another job"), ("description", ""),
                             ("validThrough", "2020-01-01")]:
            row = posting()
            row[field] = value
            bad.append([row])
        bad += [[], [posting(), posting()]]
        for posts in bad:
            with self.subTest(posts=posts):
                self.posts = posts
                self.assertEqual(self.run_reader(), [])

    def test_redirected_or_unrelated_result_rejected(self):
        self.final_override = LISTING
        self.assertEqual(self.run_reader(), [])
        self.final_override = None
        self.assertEqual(self.run_reader("xyznichtvorhanden"), [])

    def test_duplicate_records_and_empty_list(self):
        self.rows *= 2
        self.assertEqual(len(self.run_reader()), 1)
        self.assertEqual(len(self.calls), 4)
        self.rows = []
        self.assertEqual(self.run_reader(), [])
        self.assertEqual(self.report["filtered"], 0)

    def test_malformed_api_structure_fails_explicitly(self):
        original = self.get
        for body in ['not JSON', '{"jobPostings":{}}', '{"jobPostings":[null]}']:
            with self.subTest(body=body):
                def get(raw, source, **options):
                    return (raw, body) if raw == API else original(raw, source, **options)
                with self.assertRaises(FetchError) as error:
                    list(bite(self.source, SimpleNamespace(q=""), get, {"filtered": 0}))
                self.assertEqual(error.exception.code, "unsupported")

    def test_at_most_ten_unique_detail_documents(self):
        self.rows = [listing(f"{i:040x}") for i in range(12)]
        # They fail identity checks, but still consume the detail allowance.
        self.assertEqual(self.run_reader(), [])
        self.assertEqual(len(self.calls), 13)

    def fixture_transport(self, budget):
        outer = self

        class FixtureTransport:
            def __init__(self):
                self.budget, self.last = budget, {}

            def get(self, raw, hosts, authorize=None, **options):
                if authorize:
                    authorize(raw)
                self.budget.claim()
                if raw.endswith("/robots.txt"):
                    return raw, outer.robots
                return outer.get(raw, outer.source, **options)
        return FixtureTransport()

    def test_crawler_approval_robots_and_shared_budget(self):
        req = SimpleNamespace(q="Digitalisierung", location="", sources=["zfp_winnenden"])
        self.robots = "User-agent: *\nAllow: /\nDisallow: /*/*/*/apply"
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": ""}):
            result = crawl(req, self.fixture_transport)
        self.assertEqual(result["documents"], 0)
        self.assertEqual(result["sources"][0]["status"], "not_approved")
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "zfp_winnenden"}):
            result = crawl(req, self.fixture_transport)
            self.assertEqual(len(result["jobs"]), 1)
            self.assertEqual(result["documents"], 8)
            self.robots = "User-agent: *\nDisallow: /"
            result = crawl(req, self.fixture_transport)
            self.assertEqual(result["sources"][0]["status"], "robots_denied")
            with patch("crawler.Budget", side_effect=lambda: Budget(documents=1)):
                self.robots = "User-agent: *\nAllow: /"
                result = crawl(req, self.fixture_transport)
                self.assertEqual(result["sources"][0]["status"], "request_limit")

    def test_missing_robots_on_asset_or_api_stops_reader(self):
        req = SimpleNamespace(q="", location="", sources=["zfp_winnenden"])
        original = self.fixture_transport
        for host in ["cs-assets.b-ite.com", "jobs.b-ite.com"]:
            self.robots = "User-agent: *\nAllow: /"
            def factory(budget):
                transport = original(budget)
                get = transport.get
                def fail(raw, *args, **kwargs):
                    if raw == "https://" + host + "/robots.txt":
                        budget.claim()
                        raise FetchError("gone")
                    return get(raw, *args, **kwargs)
                transport.get = fail
                return transport
            with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "zfp_winnenden"}):
                result = crawl(req, factory)
            self.assertEqual(result["sources"][0]["status"], "robots_unavailable")
            self.assertEqual(result["jobs"], [])


class JavascriptTransportTests(unittest.TestCase):
    def make_transport(self, content_type="application/javascript", status=200):
        data = io.BytesIO(b'public client configuration')
        class Connection:
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def close(self): pass
            def getresponse(self):
                return SimpleNamespace(status=status, read=data.read,
                    getheader=lambda name, default=None: {
                        "Content-Type": content_type, "Location": CONFIG}.get(name, default))
        resolve = lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))]
        return Transport(Budget(), resolve, Connection)

    def test_explicit_javascript_mode_only(self):
        with self.assertRaises(FetchError):
            self.make_transport().get(CONFIG, ("cs-assets.b-ite.com",))
        _, text = self.make_transport().get(CONFIG, ("cs-assets.b-ite.com",), accept_javascript=True)
        self.assertIn("configuration", text)
        for kind in ["application/octet-stream", "text/html"]:
            with self.assertRaises(FetchError):
                self.make_transport(kind).get(CONFIG, ("cs-assets.b-ite.com",), accept_javascript=True)

    def test_no_mixed_modes_or_redirects_or_unlisted_hosts(self):
        for options in [{"accept_json": True}, {"json_body": {"write": "not allowed"}}]:
            with self.assertRaises(FetchError):
                self.make_transport().get(CONFIG, ("cs-assets.b-ite.com",), accept_javascript=True, **options)
        with self.assertRaises(FetchError):
            self.make_transport(status=302).get(CONFIG, ("cs-assets.b-ite.com",), accept_javascript=True)
        with self.assertRaises(FetchError):
            self.make_transport().get(CONFIG, ("jobs.b-ite.com",), accept_javascript=True)


if __name__ == "__main__":
    unittest.main()
