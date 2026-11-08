import os
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from crawler import crawl
from safe_http import FetchError
from search_outcomes import festo_no_matches
from sources import registry


# Minimal structure transcribed from Festo's public Immobilien search.
EMPTY = """<h1 class="keyword-title">Search results for "Immobilien".</h1>
<div id="noresults" lang="en-GB" class="alert alert-block">
<div id="attention"><label><mark>There are currently no open positions matching </mark>
<mark>"<span class="attention securitySearchString">Immobilien</span>".</mark></label></div>
<div id="noresults-message"><label>The 10 most recent jobs posted by Festo SE &amp; Co. KG
are listed below for your convenience.</label></div></div>
<form name="keywordsearch"><input name="q" value="Immobilien"></form>
<a href="/job/St_-Ingbert-Praktikum-technisch/854296901">Praktikum</a>
<a rel="next" href="/search/?q=Immobilien&amp;startrow=10">Next</a>"""


class EmptySearchTests(unittest.TestCase):
    def setUp(self):
        self.source = registry()["festo"]

    def test_explicit_matching_empty_search(self):
        self.assertTrue(festo_no_matches(EMPTY, self.source, "Immobilien"))
        self.assertTrue(festo_no_matches(EMPTY, self.source, " IMMOBILIEN "))

    def test_shell_missing_proof_stale_search_and_other_source_are_not_empty(self):
        for html in ["<app-root></app-root>", "<p>No jobs</p>",
                     EMPTY.replace("There are currently no open positions matching", "Search results"),
                     EMPTY.replace("most recent jobs", "matching jobs"),
                     EMPTY.replace('value="Immobilien"', 'value="Software"'),
                     EMPTY.replace('id="noresults"', 'id="noresults" hidden'),
                     EMPTY.replace('id="noresults"', 'id="noresults" style="display: none"'),
                     EMPTY + '<div id="noresults"></div>']:
            self.assertFalse(festo_no_matches(html, self.source, "Immobilien"), html[:100])
        self.assertFalse(festo_no_matches(EMPTY, self.source, "Software"))
        self.assertFalse(festo_no_matches(EMPTY, self.source, ""))
        self.assertFalse(festo_no_matches(EMPTY, replace(self.source, key="bosch"), "Immobilien"))

    def run_crawl(self, html=EMPTY, robots="User-agent: *\nAllow: /", detail=None, next_html=None):
        self.calls = []
        outer = self
        class FakeTransport:
            def __init__(self, budget):
                self.budget, self.last = budget, {}
            def get(self, raw, hosts, authorize=None, **options):
                if authorize:
                    authorize(raw)
                self.budget.claim()
                outer.calls.append(raw)
                if raw.endswith("/robots.txt"):
                    return raw, robots
                if "/job/" in raw:
                    if detail is None:
                        raise AssertionError("Empty search must not fetch recommendation details")
                    return raw, detail
                if next_html is not None and "startrow=10" in raw:
                    return raw, next_html
                return raw, html
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "festo"}):
            return crawl(SimpleNamespace(q="Immobilien", location="", sources=["festo"]), FakeTransport)

    def test_no_matches_uses_two_documents_and_never_follows_recommendations(self):
        result = self.run_crawl()
        self.assertEqual(result["jobs"], [])
        self.assertEqual(result["documents"], 2)
        self.assertEqual(result["sources"][0], {
            "source": "festo", "label": "Festo", "status": "no_matches", "kept": 0, "filtered": 0})
        self.assertFalse(any("/job/" in raw for raw in self.calls))

    def test_robots_denied_is_not_relabelled_as_no_matches(self):
        result = self.run_crawl(robots="User-agent: *\nDisallow: /")
        self.assertEqual(result["sources"][0]["status"], "robots_denied")
        self.assertEqual(result["documents"], 1)

    def test_unverified_shell_remains_unsupported(self):
        result = self.run_crawl(html="<app-root></app-root>")
        self.assertEqual(result["sources"][0]["status"], "unsupported")

    def test_real_matching_job_remains_extractable(self):
        detail = """<script type="application/ld+json">{"@type":"JobPosting",
        "title":"Immobilien Manager","hiringOrganization":{"name":"Festo SE & Co. KG"},
        "description":"Immobilien verwalten am veröffentlichten Standort.",
        "jobLocation":{"address":{"addressLocality":"Esslingen","addressCountry":"DE"}}}</script>"""
        result = self.run_crawl(html='<a href="/job/immobilien-manager/12345">Immobilien Manager</a>', detail=detail)
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["documents"], 3)

    def test_empty_later_page_does_not_discard_already_found_jobs(self):
        detail = """<script type="application/ld+json">{"@type":"JobPosting",
        "title":"Immobilien Manager","hiringOrganization":{"name":"Festo SE & Co. KG"},
        "description":"Immobilien verwalten.","jobLocation":{"address":{"addressCountry":"DE"}}}</script>"""
        result = self.run_crawl(
            html='<a href="/job/immobilien-manager/12345">Immobilien</a>'
                 '<a rel="next" href="/search/?q=Immobilien&amp;startrow=10">Next</a>',
            detail=detail, next_html=EMPTY)
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["documents"], 4)


if __name__ == "__main__":
    unittest.main()
