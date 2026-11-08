"""Reduced public Carsonal shapes, synthetic prose; no real client search keys."""
import copy
import io
import json
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from carsonal_adapter import (EMPLOYER, ENV, OWNER, PAGE_ID, ROOT, TENANT,
                              APP_ID, INDEX, SEARCH_HOST, SEARCH_PATH, carsonal,
                              missing_robots_scope, public_context, verified_publication)
from crawler import crawl
from safe_http import Budget, FetchError, Transport
from sources import registry


REF = "VO2026-006538"
SLUG = "praktikum-automobilkaufmann-mwd-fuer-alle-standorte-" + REF
TITLE = "Praktikum Automobilkaufmann (m/w/d) für ALLE Standorte"


def tenant():
    return {"type": "career_pages", "id": PAGE_ID, "attributes": {
        "custom_domain": "jobs.burgerschloz.de", "custom_domain_status": "READY",
        "contact_company_name": EMPLOYER}}


def hit():
    return {"objectID": "110075", "career_page_id": 12, "reference_code": REF,
            "seo_publication_identifier": SLUG, "job_posting_title": TITLE,
            "start_date": 1700000000, "end_date": 0}


def publication():
    return {"data": {"type": "publications", "id": "110075", "attributes": {
        "reference_code": REF, "seo_publication_identifier": SLUG, "start_date": "2023-11-14T22:13:20Z",
        "settings": {"channel": "CAREER_PAGE"}, "job_posting": {
            "title": TITLE, "tasks": {"headline": "Aufgaben", "content": "<p>Praxis im kaufmännischen Bereich.</p>"}},
        "workplace": {"company_name": EMPLOYER, "city": "Schorndorf", "zip": "73614", "country": "DE"}},
        "relationships": {"career_page": {"data": {"type": "career_pages", "id": PAGE_ID}}}},
        "included": [tenant()]}


def root_document():
    return {"links": {
        "public_career_page": {"href": ROOT + "/public/career_page-{domain}"},
        "public_career_page_publication": {"href": ROOT + "/public/career_page-{domain}/publication-{reference_code}"}},
        "meta": {"algolia": {"app_id": APP_ID, "api_key": "a" * 32, "indices": {INDEX: INDEX}}}}


def search_url(**overrides):
    params = {"query": "Automobilkaufmann", "facetFilters": '[["career_page_id:12"]]',
              "filters": "start_date <= 1800000000 AND (end_date = 0 OR end_date >= 1800000000)",
              "hitsPerPage": "20", "page": "0", "x-algolia-application-id": APP_ID,
              "x-algolia-api-key": "a" * 32}
    params.update(overrides)
    return "https://" + SEARCH_HOST + SEARCH_PATH + "?" + urlencode(params)


class CarsonalTests(unittest.TestCase):
    def setUp(self):
        self.source = replace(registry()["burger_schloz"], adapter="carsonal", api=ROOT,
                              search=OWNER + "/de/", hosts=("jobs.burgerschloz.de", "api.carsonal.de"),
                              detail=r"^/de/jobs/[a-z0-9-]+-VO[0-9]{4}-[0-9]{6}$")
        self.options = {"accept_json": True, "json_api": True}

    def test_real_document_shape_and_explicit_workplace(self):
        job = verified_publication(publication(), hit(), self.source, "Automobilkaufmann")
        self.assertEqual(job["company"], EMPLOYER)
        self.assertEqual(job["location"], "73614 Schorndorf DE")
        self.assertEqual(job["url"], OWNER + "/de/jobs/" + SLUG)
        self.assertIsNone(verified_publication(publication(), hit(), self.source, "xyznichtvorhanden"))

    def test_published_company_whitespace_is_not_a_foreign_employer(self):
        doc = publication()
        doc["data"]["attributes"]["workplace"]["company_name"] += " "
        doc["included"][0]["attributes"]["contact_company_name"] = " " + EMPLOYER + "\n"
        job = verified_publication(doc, hit(), self.source, "")
        self.assertEqual(job["company"], EMPLOYER)

    def test_index_identity_scope_and_dates(self):
        for field, value in [("career_page_id", 13), ("objectID", "foreign"),
                             ("reference_code", "other"), ("start_date", 9999999999),
                             ("end_date", 1), ("end_date", True),
                             ("seo_publication_identifier", "../apply-" + REF)]:
            row = hit()
            row[field] = value
            with self.subTest(field=field):
                self.assertIsNone(verified_publication(publication(), row, self.source, ""))

    def test_public_document_must_confirm_index_and_employer(self):
        cases = []
        for field, value in [("id", "110076"), ("type", "authorized_publications")]:
            doc = publication()
            doc["data"][field] = value
            cases.append(doc)
        for field, value in [("reference_code", "VO2026-000001"), ("seo_publication_identifier", "wrong"),
                             ("settings", {"channel": "WEBSITE_WIDGET"}),
                             ("start_date", "2099-01-01T00:00:00Z")]:
            doc = publication()
            doc["data"]["attributes"][field] = value
            cases.append(doc)
        doc = publication()
        doc["data"]["relationships"]["career_page"]["data"]["id"] = "13"
        cases.append(doc)
        doc = publication()
        doc["included"][0]["attributes"]["custom_domain"] = "other.example"
        cases.append(doc)
        for field, value in [("company_name", "Other Dealer"), ("company_name", "")]:
            doc = publication()
            doc["data"]["attributes"]["workplace"][field] = value
            cases.append(doc)
        doc = publication()
        doc["data"]["attributes"]["job_posting"]["tasks"]["content"] = ""
        doc["data"]["attributes"]["job_posting"]["tasks"]["headline"] = ""
        cases.append(doc)
        for doc in cases:
            with self.subTest(doc=doc):
                self.assertIsNone(verified_publication(doc, hit(), self.source, ""))

    def test_initiative_and_multiple_tenants_are_not_jobs(self):
        doc, row = publication(), hit()
        doc["data"]["attributes"]["job_posting"]["title"] = row["job_posting_title"] = "Initiativbewerbung"
        self.assertIsNone(verified_publication(doc, row, self.source, ""))
        doc = publication()
        doc["included"].append(tenant())
        self.assertIsNone(verified_publication(doc, hit(), self.source, ""))

    def test_404_scope_is_only_fixed_public_gets_for_this_source(self):
        self.assertTrue(missing_robots_scope(ROOT, self.source, {"accept_json": True}))
        self.assertTrue(missing_robots_scope(TENANT, self.source, self.options))
        self.assertTrue(missing_robots_scope(TENANT + "/publication-" + REF, self.source, self.options))
        for raw in [TENANT.replace("jobs.burgerschloz.de", "other.example"),
                    ROOT + "/authorized/career_pages/12", ROOT + "/public/job_applications",
                    TENANT + "/publication-" + REF + "/apply", TENANT + "?foreign=1",
                    TENANT.replace("https:", "http:"), TENANT.replace("api.carsonal.de", "127.0.0.1"),
                    TENANT.replace("api.carsonal.de", "user:pass@api.carsonal.de"),
                    TENANT + "#fragment"]:
            self.assertFalse(missing_robots_scope(raw, self.source, self.options), raw)
        for options in [{"accept_json": True}, {"accept_json": True, "json_api": True, "json_body": {}}]:
            self.assertFalse(missing_robots_scope(TENANT, self.source, options))
        self.assertFalse(missing_robots_scope(TENANT, replace(self.source, key="another"), self.options))

    def test_search_exception_is_exactly_one_index_and_employer_filter(self):
        opts = {"accept_json": True}
        self.assertTrue(missing_robots_scope(search_url(), self.source, opts))
        for updates in [{"facetFilters": '[["career_page_id:13"]]'}, {"page": "1"},
                        {"hitsPerPage": "100"}, {"filters": "start_date > 0"},
                        {"x-algolia-application-id": "FOREIGN"}, {"extra": "1"}]:
            self.assertFalse(missing_robots_scope(search_url(**updates), self.source, opts))
        for raw in [search_url().replace(INDEX, "another_index"),
                    search_url().replace(SEARCH_HOST, "other.algolia.net"),
                    search_url() + "&page=0"]:
            self.assertFalse(missing_robots_scope(raw, self.source, opts))
        self.assertFalse(missing_robots_scope(search_url(), self.source, {**opts, "json_body": {}}))

    def reader_get(self, raw, source, **options):
        self.calls.append(raw)
        if raw == source.search:
            return raw, '<script src="assets/env.js"></script>'
        if raw == ENV:
            self.assertEqual(options, {"accept_javascript": True})
            return raw, """BACKEND_DOMAIN:'api.carsonal.de',BACKEND_API_PATH:'/rest',BACKEND_PROTOCOL:'https://'"""
        if raw == ROOT:
            return raw, json.dumps(self.root)
        if raw == TENANT:
            return raw, json.dumps({"data": tenant()})
        if raw.startswith("https://" + SEARCH_HOST):
            self.assertEqual(options, {"accept_json": True})
            self.assertTrue(missing_robots_scope(raw, source, options))
            self.assertEqual(parse_qs(urlsplit(raw).query)["query"], ["Automobilkaufmann"])
            return raw, json.dumps({"hits": self.hits})
        self.assertRegex(raw, r"^" + TENANT.replace(".", r"\.") + r"/publication-VO[0-9]{4}-[0-9]{6}$")
        if self.gone:
            raise FetchError("gone", http_status=404)
        return raw, json.dumps(self.document)

    def run_reader(self):
        self.report = {"filtered": 0}
        return list(carsonal(self.source, SimpleNamespace(q="Automobilkaufmann"), self.reader_get, self.report))

    def setup_reader(self):
        self.calls, self.hits, self.document, self.root, self.gone = [], [hit()], publication(), root_document(), False

    def test_complete_reader_uses_one_bounded_public_search(self):
        self.setup_reader()
        self.assertEqual(len(self.run_reader()), 1)
        self.assertEqual(len(self.calls), 6)
        self.assertFalse(any("authorized" in raw or "/apply" in raw for raw in self.calls))
        self.assertEqual(len([raw for raw in self.calls if raw.startswith("https://" + SEARCH_HOST)]), 1)

    def test_unknown_search_identity_is_not_used(self):
        for field, value in [("app_id", "FOREIGN"), ("indices", {INDEX: "another"}),
                             ("api_key", "")]:
            self.setup_reader()
            self.root["meta"]["algolia"][field] = value
            with self.assertRaises(FetchError):
                self.run_reader()
            self.assertFalse(any(raw.startswith("https://" + SEARCH_HOST) for raw in self.calls))

    def test_search_shape_duplicates_gone_and_detail_limit(self):
        self.setup_reader()
        self.hits = [hit(), hit()]
        self.assertEqual(len(self.run_reader()), 1)
        self.assertEqual(len(self.calls), 6)
        self.setup_reader()
        self.gone = True
        self.assertEqual(self.run_reader(), [])
        self.assertEqual(self.report["filtered"], 1)
        self.setup_reader()
        self.hits = [{**hit(), "reference_code": f"VO2026-{i:06d}"} for i in range(12)]
        self.assertEqual(self.run_reader(), [])
        self.assertEqual(len(self.calls), 15)
        self.setup_reader()
        self.hits = [hit()] * 21
        with self.assertRaises(FetchError):
            self.run_reader()
        self.assertEqual(len(self.calls), 5)

    def test_complete_crawler_budgets_and_unapproved_source(self):
        self.setup_reader()
        outer = self
        def factory(budget):
            class FixtureTransport:
                def __init__(self):
                    self.last, self.budget = {}, budget
                def get(self, raw, hosts, authorize=None, **options):
                    if authorize:
                        authorize(raw)
                    budget.claim()
                    if raw.endswith("/robots.txt"):
                        if raw == OWNER + "/robots.txt":
                            return raw, "User-agent: *\nAllow: /"
                        outer.assertEqual(options, {"robots_request": True})
                        raise FetchError("gone", http_status=404)
                    return outer.reader_get(raw, outer.source, **options)
            return FixtureTransport()
        # Use the actual profile: no implicit host expansion by the test.
        self.source = registry()["burger_schloz"]
        req = SimpleNamespace(q="Automobilkaufmann", location="", sources=["burger_schloz"])
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": ""}):
            result = crawl(req, factory)
        self.assertEqual(result["documents"], 0)
        self.assertEqual(result["sources"][0]["status"], "not_approved")
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "burger_schloz"}):
            result = crawl(req, factory)
            self.assertEqual(len(result["jobs"]), 1)
            self.assertEqual(result["documents"], 9)
            with patch("crawler.Budget", side_effect=lambda: Budget(documents=4)):
                result = crawl(req, factory)
            self.assertEqual(result["sources"][0]["status"], "request_limit")

    def test_official_owner_and_entrypoint_evidence_required(self):
        root = {"links": {
            "public_career_page": {"href": ROOT + "/public/career_page-{domain}"},
            "public_career_page_publication": {"href": ROOT + "/public/career_page-{domain}/publication-{reference_code}"}}}
        calls = []
        def get(raw, source, **options):
            calls.append(raw)
            if raw == source.search:
                return raw, '<script src="assets/env.js"></script>'
            if raw == ENV:
                return raw, """BACKEND_DOMAIN:'api.carsonal.de',BACKEND_API_PATH:'/rest',BACKEND_PROTOCOL:'https://'"""
            return raw, json.dumps(root if raw == ROOT else {"data": tenant()})
        self.assertEqual(public_context(self.source, get), root)
        self.assertEqual(calls, [self.source.search, ENV, ROOT, TENANT])
        root["links"]["public_career_page"]["href"] = "https://other.example"
        with self.assertRaises(FetchError):
            public_context(self.source, get)

    def fixture(self, robots_status):
        outer = self
        def factory(budget):
            class FixtureTransport:
                def __init__(self):
                    self.last, self.budget = {}, budget
                def get(self, raw, hosts, authorize=None, **options):
                    if authorize:
                        authorize(raw)
                    budget.claim()
                    if raw.endswith("/robots.txt"):
                        if raw.startswith("https://api.carsonal.de"):
                            if isinstance(robots_status, int):
                                raise FetchError("gone" if robots_status in {404, 410} else "upstream_error",
                                                 http_status=robots_status)
                            return raw, robots_status
                        return raw, "User-agent: *\nAllow: /"
                    if raw == ROOT:
                        outer.root_reads += 1
                    return raw, "{}"
            return FixtureTransport()
        return factory

    def test_crawler_only_404_not_410_406_or_server_errors(self):
        req = SimpleNamespace(q="Technik", location="", sources=["burger_schloz"])
        def read(source, req, get, report):
            get(ROOT, source, accept_json=True)
            return iter([])
        for status in [404, 410, 401, 403, 406, 429, 500, 503,
                       "User-agent: *\nDisallow: /", "not a robots file"]:
            self.root_reads = 0
            with self.subTest(status=status), patch("crawler.registry", return_value={"burger_schloz": self.source}), \
                    patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "burger_schloz"}), \
                    patch("crawler.adapter_jobs", side_effect=read):
                result = crawl(req, self.fixture(status))
            self.assertEqual(self.root_reads, 1 if status == 404 else 0)
            self.assertEqual(result["sources"][0]["status"],
                             "done" if status == 404 else "robots_denied" if isinstance(status, str) and "Disallow" in status
                             else "robots_unavailable")

    def test_missing_robots_cache_does_not_authorize_other_paths(self):
        req = SimpleNamespace(q="Technik", location="", sources=["burger_schloz"])
        for raw, options in [(ROOT + "/authorized/users", {"accept_json": True}),
                             (ROOT, {"accept_json": True, "json_body": {"write": True}})]:
            def read(source, req, get, report):
                get(ROOT, source, accept_json=True)
                get(raw, source, **options)
                return iter([])
            self.root_reads = 0
            with patch("crawler.registry", return_value={"burger_schloz": self.source}), \
                    patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "burger_schloz"}), \
                    patch("crawler.adapter_jobs", side_effect=read):
                result = crawl(req, self.fixture(404))
            self.assertEqual(result["sources"][0]["status"], "robots_unavailable")
            self.assertEqual(self.root_reads, 1)


class ResponseTests(unittest.TestCase):
    def transport(self, status=200, kind="text/plain"):
        body = io.BytesIO(b"User-agent: *\nAllow: /")
        outer = self
        class Connection:
            def __init__(self, *args): pass
            def close(self): pass
            def request(self, *args, **kwargs):
                outer.headers = kwargs["headers"]
            def getresponse(self):
                return SimpleNamespace(status=status, read=body.read,
                    getheader=lambda name, default=None: {"Content-Type": kind, "Location": ROOT}.get(name, default))
        return Transport(Budget(), lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))], Connection)

    def test_direct_status_distinguishes_404_and_410(self):
        for status in [404, 410, 406, 500]:
            with self.subTest(status=status), self.assertRaises(FetchError) as error:
                self.transport(status).get("https://api.carsonal.de/robots.txt", ("api.carsonal.de",), robots_request=True)
            self.assertEqual(error.exception.http_status, status)
            self.assertEqual(self.headers["Accept"], "*/*")

    def test_robots_mode_does_not_follow_redirects_or_accept_other_paths(self):
        with self.assertRaises(FetchError) as error:
            self.transport(302).get("https://api.carsonal.de/robots.txt", ("api.carsonal.de",), robots_request=True)
        self.assertIsNone(error.exception.http_status)
        for raw in [ROOT, "https://api.carsonal.de/robots.txt?other=1"]:
            with self.assertRaises(FetchError):
                self.transport().get(raw, ("api.carsonal.de",), robots_request=True)

    def test_vendor_json_mode_is_read_only_and_explicit(self):
        self.transport(kind="application/vnd.api+json").get(TENANT, ("api.carsonal.de",), accept_json=True, json_api=True)
        self.assertEqual(self.headers["Accept"], "application/vnd.api+json")
        with self.assertRaises(FetchError):
            self.transport().get(TENANT, ("api.carsonal.de",), accept_json=True, json_api=True, json_body={})


if __name__ == "__main__":
    unittest.main()
