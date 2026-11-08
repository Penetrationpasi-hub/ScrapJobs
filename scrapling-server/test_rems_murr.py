import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from sources import registry, approved_sources
from extraction import discovery, extract
from crawler import crawl


class RemsMurrTest(unittest.TestCase):
    def setUp(self):
        self.source = registry()["rems_murr_jobs"]
        self.url = "https://rems-murr-jobs.de/job/produktionsmitarbeiter-12345"
        self.html = '<script type="application/ld+json">' + json.dumps({
            "@type": "JobPosting", "title": "Produktionsmitarbeiter",
            "hiringOrganization": {"name": "Testarbeitgeber GmbH"},
            "jobLocation": {"address": {"addressLocality": "Backnang", "postalCode": "71522", "addressCountry": "DE"}},
            "description": "Konkrete Aufgaben und Anforderungen. " * 60,
        }) + "</script>"

    def test_only_job_details_and_short_excerpt_with_original_link(self):
        source = self.source
        self.assertEqual(source.start("Produktion & Montage", "Backnang"),
                         "https://rems-murr-jobs.de/jobs?search=Produktion%20%26%20Montage")
        links, _ = discovery('<a href="' + self.url + '">Produktion</a>'
                             '<a href="/jobs/produktion/backnang">Übersicht</a>'
                             '<a href="https://evil.test/job/produktion-123">Andere</a>',
                             source.search, source, "Produktion")
        self.assertEqual(links, [self.url])
        job = extract(self.html, self.url, source, "Produktion")
        self.assertEqual(job["url"], self.url)
        self.assertIn("Backnang", job["location"])
        self.assertLessEqual(len(job["description"]), 482)
        self.assertTrue(job["description"].endswith(" …"))
        self.assertIsNone(extract(self.html, "https://rems-murr-jobs.de/jobs/produktion/backnang", source, "Produktion"))

    def test_explicit_board_approval_and_separate_worker_group(self):
        from main import Search
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            self.assertNotIn(self.source.key, approved_sources())
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers,rems_murr_jobs"}):
            self.assertIn(self.source.key, approved_sources())
        self.assertEqual(Search.validate_sources(["rems_murr_jobs"]), ["rems_murr_jobs"])
        with self.assertRaises(ValueError):
            Search.validate_sources(["rems_murr_jobs", "festo"])

    def test_crawler_respects_ten_second_delay_without_real_sleep(self):
        clock = [100.0]
        pauses = []
        source, detail, html = self.source, self.url, self.html
        def sleep(seconds):
            pauses.append(seconds)
            clock[0] += seconds
        def factory(budget):
            class Fixture:
                def __init__(self):
                    self.last = {}
                def get(self, raw, hosts, authorize=None, **options):
                    if authorize:
                        authorize(raw)
                    budget.claim()
                    self.last[urlsplit(raw).hostname] = clock[0]
                    if raw.endswith("/robots.txt"):
                        return raw, "User-agent: *\nCrawl-delay: 10\nAllow: /"
                    if raw == detail:
                        return raw, html
                    return raw, '<a href="' + detail + '">Produktion</a>'
            return Fixture()
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": source.key}), \
                patch("crawler.time.monotonic", side_effect=lambda: clock[0]), \
                patch("crawler.time.sleep", side_effect=sleep):
            result = crawl(SimpleNamespace(q="Produktion", location="Backnang", sources=[source.key]), factory)
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(pauses, [10, 10])
        self.assertEqual(result["documents"], 3)
