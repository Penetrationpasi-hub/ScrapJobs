"""Offline regression checks. No employer or job-board requests are made."""
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from crawler import crawl
from extraction import discovery, extract, is_detail
from safe_http import Budget
from sources import registry, approved_sources
from main import Search, sources as source_endpoint


class EmployerCatalog(unittest.TestCase):
    def test_entire_uploaded_list_accounted_for_without_duplicate_sources(self):
        rows = json.loads(Path(__file__).with_name("employers.json").read_text())
        entries = [entry for row in rows for entry in row["entries"]]
        # Entry 36 (Bosch Murrhardt) uses the existing Bosch group adapter.
        # The user explicitly excluded these five employers after no public
        # careers source could be found. Hahn and Klingele are separate sources.
        excluded = {29, 32, 37, 50, 60}
        self.assertEqual(set(entries) | {36}, set(range(1, 65)) - excluded)
        self.assertEqual(len(entries), len(set(entries)))
        configured = registry()
        self.assertGreater(len(configured), 50)
        self.assertEqual(len(configured), len({row.key for row in configured.values()}))
        for key in ("zvw", "mercedes_benz", "stihl", "mahle", "frech", "elanders", "pfisterer", "tti",
                    "mulfinger", "stadtwerke_waiblingen", "benz_sport", "eisenmann", "riani",
                    "dusyma", "awrm", "hahn_automobile", "klingele"):
            self.assertTrue(configured[key].available)
        self.assertTrue(configured["murrelektronik"].available)
        self.assertFalse(configured["signalhorn"].available)
        for key in ("irmscher", "winwin_office", "picksraus", "falkenstein", "link_chemie"):
            self.assertNotIn(key, configured)

    def test_no_approval_by_default_and_employer_group_excludes_boards_and_unconfigured(self):
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": ""}):
            self.assertEqual(approved_sources(), set())
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": " employers, unknown, irmscher "}):
            approved = approved_sources()
            self.assertIn("stihl", approved)
            self.assertNotIn("indeed", approved)
            self.assertNotIn("stepstone", approved)
            self.assertNotIn("irmscher", approved)
            self.assertNotIn("unknown", approved)

    def test_source_status_matches_actual_crawler_approval(self):
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            rows = source_endpoint()["sources"]
            self.assertEqual({row["key"] for row in rows if row["approved"]}, approved_sources())
            self.assertTrue(all(not row["approved"] for row in rows if not row["available"]))
            self.assertEqual(source_endpoint()["maxSourcesPerRun"], 4)

    def test_unknown_and_five_sources_rejected_before_crawling(self):
        base = dict(q="Elektronik", location="Waiblingen", radius_km=25, id="a" * 64)
        for chosen in (["unknown"], ["stihl"] * 2, ["stihl", "mahle", "frech", "rems", "bosch"]):
            with self.assertRaises(ValueError):
                Search(**base, sources=chosen)
        self.assertEqual(Search(**base, sources=["stihl", "frech"]).sources, ["stihl", "frech"])

    def test_unconfigured_source_never_fetches_even_if_manually_approved(self):
        class NoRequests:
            def __init__(self, budget):
                pass
            def get(self, *args, **kwargs):
                raise AssertionError("Unconfigured source must not make HTTP requests")
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "signalhorn,employers"}):
            result = crawl(SimpleNamespace(q="Elektriker", location="", sources=["signalhorn"]), NoRequests)
        self.assertEqual(result["documents"], 0)
        self.assertEqual(result["sources"][0]["status"], "not_configured")

    def test_exact_tenants_and_career_indexes_are_not_ads(self):
        configured = registry()
        examples = {
            "stihl": "https://corporate.stihl.de/de/karriere/stellenangebote/job-details/werkstudent-elektronik-sf58524",
            "paulinenpflege": "https://jobs.paulinenpflege.de/Diaetassistent-mwd-de-j3459.html",
            "stadt_schorndorf": "https://karriere.schorndorf.de/Ausbildung-Fachkraft-de-j1232.html",
            "frech": "https://www.frech.com/de/job-details-de/it-projektmanager-m-w-d.html",
            "wirmachendruck": "https://jobs.wir-machen-druck.de/de/jobs/30275/crm-manager-mwd",
            "pfisterer": "https://pfisterer.mhm.jobs/1786-data-strategist/job.html",
            "elanders": "https://jobapplication.hrworks.de/de?companyId=av679e8c&id=06276f",
            "robert_bosch_krankenhaus": "https://jobs.smartrecruiters.com/RobertBoschKrankenhausGmbH/123-test",
        }
        for key, url in examples.items():
            with self.subTest(key=key):
                self.assertTrue(is_detail(url, configured[key]))
                self.assertFalse(is_detail(configured[key].start("", ""), configured[key]))
                posting = {"@type": "JobPosting", "title": "Elektroniker", "hiringOrganization": {"name": "Beispiel GmbH"}, "url": url}
                html = '<script type="application/ld+json">' + json.dumps(posting) + "</script>"
                self.assertIsNotNone(extract(html, url, configured[key], "Elektro"))
                self.assertIsNone(extract(html, url.replace(url.split("/")[2], "evil.test"), configured[key]))
        self.assertFalse(is_detail("https://jobapplication.hrworks.de/de?companyId=other&id=06276f", configured["elanders"]))
        self.assertFalse(is_detail("https://jobs.smartrecruiters.com/AnotherCompany/123-test", configured["robert_bosch_krankenhaus"]))

    def test_relevant_links_are_prioritized_without_more_requests(self):
        source = registry()["stihl"]
        base = source.start("", "")
        html = ('<a href="/de/karriere/stellenangebote/job-details/marketing-sf1">Marketing</a>'
                '<a href="/de/karriere/stellenangebote/job-details/technik-sf2">Elektroniker</a>')
        links, _ = discovery(html, base, source, "Elektro")
        self.assertIn("technik-sf2", links[0])

    def test_query_cannot_modify_path_or_add_query_parameters(self):
        url = registry()["mahle"].start("Elektro/foo&evil=1", "Ort/../../bad")
        self.assertIn("Elektro%2Ffoo%26evil%3D1", url)
        self.assertIn("Ort%2F..%2F..%2Fbad", url)

    def test_initiativbewerbung_is_not_a_concrete_vacancy(self):
        source = registry()["frech"]
        url = "https://www.frech.com/de/job-details-de/initiativbewerbung.html"
        html = '<script type="application/ld+json">' + json.dumps({
            "@type": "JobPosting", "title": "Initiativbewerbung", "hiringOrganization": {"name": "Firma GmbH"}
        }) + "</script>"
        self.assertIsNone(extract(html, url, source))

    def test_shared_airbus_portal_does_not_leak_other_employers_into_tesat(self):
        source = registry()["tesat"]
        url = "https://ag.wd3.myworkdayjobs.com/de-DE/Airbus/job/Backnang/Elektroniker_JR123"
        posting = {"@type": "JobPosting", "title": "Elektroniker", "hiringOrganization": {"name": "Airbus Operations"}}
        html = lambda: '<script type="application/ld+json">' + json.dumps(posting) + "</script>"
        self.assertIsNone(extract(html(), url, source))
        posting["hiringOrganization"]["name"] = "TESAT-Spacecom GmbH & Co. KG"
        self.assertIsNotNone(extract(html(), url, source))

    def test_existing_global_budget_is_unchanged(self):
        self.assertEqual(Budget().remaining, 40)
