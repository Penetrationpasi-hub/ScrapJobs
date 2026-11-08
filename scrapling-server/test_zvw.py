"""Offline checks for Zeitungsverlag Waiblingen. The fixture is the verified markup of
karriere.zvw.de/stellenangebote (abridged); no network access happens here."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from crawler import crawl
from extraction import discovery, extract
from sources import registry

ADS = {
    "https://rems-murr-jobs.de/job/markenbotschafterin-mwd-1805688": "Markenbotschafter:in m/w/d",
    "https://rems-murr-jobs.de/job/ausbildung-2026-medienkauffrau-mann-digital-und-print-1209766": "Ausbildung Medienkauffrau/-mann digital und Print",
}
INDEX = "".join(
    f'<div class="elementor-image-box-content"><h4 class="elementor-image-box-title"><a href="{u}" target="_blank">{t}</a></h4></div>'
    for u, t in ADS.items()
) + ('<a href="https://karriere.zvw.de/praktika/">Praktika</a>'
     '<a href="https://evil.test/job/fake-123">Fremd</a>'
     '<a href="https://rems-murr-jobs.de/jobs/produktion/backnang">Übersicht</a>'
     '<a href="mailto:karriere@zvw.de">Initiativbewerbung</a>')


def posting(title, company="Zeitungsverlag GmbH & Co Waiblingen KG"):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": title, "hiringOrganization": {"name": company},
        "jobLocation": {"address": {"addressLocality": "Waiblingen", "postalCode": "71332", "addressCountry": "DE"}},
        "description": "Wir sind ein modernes Medienunternehmen. " * 40,
    }) + "</script>"


class ZvwTest(unittest.TestCase):
    def setUp(self):
        self.source = registry()["zvw"]

    def test_catalog_entry(self):
        self.assertTrue(self.source.available)
        self.assertEqual(self.source.start("Ausbildung", "Waiblingen"), "https://karriere.zvw.de/stellenangebote/")

    def test_only_job_pages_on_regional_board_are_discovered(self):
        links, _ = discovery(INDEX, self.source.search, self.source, "Ausbildung")
        self.assertEqual(sorted(links), sorted(ADS))
        self.assertIn("ausbildung", links[0])  # relevant link ranked first

    def test_posting_requires_zvw_employer(self):
        url = next(iter(ADS))
        job = extract(posting("Markenbotschafter:in m/w/d"), url, self.source, "Marken")
        self.assertEqual(job["company"], "Zeitungsverlag GmbH & Co Waiblingen KG")
        self.assertEqual(job["url"], url)
        self.assertLessEqual(len(job["description"]), 482)
        # The shared board lists other employers; they must never leak in.
        self.assertIsNone(extract(posting("Markenbotschafter:in m/w/d", "Rockstroh Fahrzeugbau GmbH"), url, self.source, "Marken"))
        self.assertIsNone(extract(posting("X"), "https://rems-murr-jobs.de/jobs/produktion/backnang", self.source))

    def test_crawl_end_to_end_with_fixture(self):
        pages = {self.source.search: INDEX, **{u: posting(t) for u, t in ADS.items()}}
        def factory(budget):
            class Fixture:
                last = {}
                def get(self, raw, hosts, authorize=None, **options):
                    if authorize:
                        authorize(raw)
                    budget.claim()
                    if raw.endswith("/robots.txt"):
                        return raw, "User-agent: *\nAllow: /"
                    self.last[urlsplit(raw).hostname] = 0
                    return raw, pages[raw]
            return Fixture()
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "zvw"}):
            result = crawl(SimpleNamespace(q="Ausbildung", location="Waiblingen", sources=["zvw"]), factory)
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual([j["title"] for j in result["jobs"]], ["Ausbildung Medienkauffrau/-mann digital und Print"])
        self.assertTrue(all(j["source"] == "Zeitungsverlag Waiblingen · Scrapling" for j in result["jobs"]))


if __name__ == "__main__":
    unittest.main()


class ZvwIsolationTest(unittest.TestCase):
    def test_zvw_is_isolated_and_not_part_of_employers_group(self):
        from sources import ISOLATED_SOURCES, approved_sources
        self.assertIn("zvw", ISOLATED_SOURCES)
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            self.assertNotIn("zvw", approved_sources())
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers,zvw"}):
            self.assertIn("zvw", approved_sources())
