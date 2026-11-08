import json
import unittest
from types import SimpleNamespace

from datafeed_adapter import clean, items
from employer_adapters import adapter_jobs
from sources import registry

FEED = {"@context": "http://schema.org", "@type": "DataFeed", "numberOfItems": 3, "dataFeedElement": [
    {"@type": "DataFeedItem", "item": {
        "@type": "JobPosting", "title": "Initiativbewerbung", "url": "https://jobs.loeffelhardt.de/jobs/18640324/Initiativbewerbung/",
        "datePosted": "2025-05-22T09:54:45.916+02:00", "description": "geheim",
        "hiringOrganization": {"@type": "Organization", "name": "Emil Löffelhardt GmbH & Co. KG"},
        "jobLocation": {"@type": "Place", "address": {"addressLocality": "-", "postalCode": "-", "addressRegion": "Baden-Württemberg"}}}},
    {"@type": "DataFeedItem", "item": {
        "@type": "JobPosting", "title": "Lagermitarbeiter (m/w/d)", "url": "https://jobs.loeffelhardt.de/jobs/68099621/Lagermitarbeiter-m-w-d-/",
        "datePosted": "2026-10-21T09:07:28.590+02:00", "description": "Beschreibung",
        "hiringOrganization": {"@type": "Organization", "name": "Emil Löffelhardt GmbH & Co. KG"},
        "jobLocation": {"@type": "Place", "address": {"addressLocality": "Schorndorf", "postalCode": "-", "addressRegion": "Baden-Württemberg"}}}},
    {"@type": "DataFeedItem", "item": {
        "@type": "JobPosting", "title": "Fremd", "url": "https://evil.test/jobs/1/x/",
        "hiringOrganization": {"name": "Emil Löffelhardt GmbH & Co. KG"}}},
]}


class DatafeedTest(unittest.TestCase):
    def test_feed_is_read_in_one_request_and_placeholders_are_dropped(self):
        source = registry()["loeffelhardt"]
        calls = []

        def get(raw, src, **options):
            calls.append(raw)
            return raw, json.dumps(FEED)

        report = {"filtered": 0, "kept": 0}
        jobs = list(adapter_jobs(source, SimpleNamespace(q="", location=""), get, report))
        self.assertEqual(calls, ["https://stellenangebot-loeffelhardt.career.softgarden.de/jobs.feed.json"])
        self.assertEqual([j["title"] for j in jobs], ["Lagermitarbeiter (m/w/d)"])
        self.assertEqual(jobs[0]["location"], "Schorndorf Baden-Württemberg")
        self.assertEqual(jobs[0]["posted"], "2026-10-21")
        self.assertEqual(report["filtered"], 2)  # Initiativbewerbung und fremder Host

    def test_clean_removes_dashes_and_descriptions(self):
        row = clean(FEED["dataFeedElement"][0]["item"])
        self.assertNotIn("description", row)
        self.assertEqual(row["jobLocation"]["address"], {"addressRegion": "Baden-Württemberg"})

    def test_rejects_other_json(self):
        with self.assertRaises(Exception):
            list(items({"foo": 1}))
