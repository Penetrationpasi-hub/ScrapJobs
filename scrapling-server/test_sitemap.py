import unittest
from types import SimpleNamespace

from employer_adapters import adapter_jobs
from sitemap_adapter import locations
from sources import registry

AD = "https://jobs.peterhahn.com/stellenangebote/Minijob-Passformmodel-m-w-d-Anprobe-Konfektionsgroesse-36-Winterbach-PETER-HAHN-GmbH--653128593"
MAP = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
       '<url><loc>https://jobs.peterhahn.com/anmeldung</loc></url><url><loc>https://jobs.peterhahn.com/jobs</loc></url>'
       f'<url><loc>{AD}</loc></url><url><loc>https://jobs.peterhahn.com/stellenangebote/x--1/bewerbung</loc></url></urlset>')
AD_HTML = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Minijob Passformmodel (m/w/d)",'
           '"hiringOrganization":{"name":"Peter Hahn GmbH"},"datePosted":"2026-11-08T07:40:57.000",'
           '"jobLocation":{"address":{"addressLocality":"Winterbach","postalCode":"73650"}}}</script>')


class SitemapTest(unittest.TestCase):
    def test_reads_only_urlset_without_doctype(self):
        self.assertIn(AD, locations(MAP))
        with self.assertRaises(Exception):
            locations('<!DOCTYPE x [<!ENTITY a "b">]><urlset><url><loc>' + AD + '</loc></url></urlset>')
        with self.assertRaises(Exception):
            locations('<sitemapindex><sitemap><loc>https://x/sitemap2</loc></sitemap></sitemapindex>')

    def test_only_matching_pages_are_fetched_and_verified(self):
        source = registry()["peter_hahn"]
        calls = []

        def get(raw, src, **options):
            calls.append((raw, options.get("accept_xml", False)))
            return (raw, MAP) if options.get("accept_xml") else (raw, AD_HTML)

        report = {"filtered": 0, "kept": 0}
        jobs = list(adapter_jobs(source, SimpleNamespace(q="", location="", max_details=10), get, report))
        self.assertEqual([j["company"] for j in jobs], ["Peter Hahn GmbH"])
        self.assertEqual([c for c, _ in calls], ["https://jobs.peterhahn.com/sitemap", AD])


class SitemapSourcesTest(unittest.TestCase):
    def test_configured_sitemap_sources_match_their_ad_addresses(self):
        from extraction import is_detail
        cases = {
            "diakonie_stetten": ("https://deinjob.diakonie-stetten.de/jobs/23893460/Mitarbeiter-m-w-d-in-der-Reinigung/", "https://deinjob.diakonie-stetten.de/"),
            "loeffelhardt": ("https://jobs.loeffelhardt.de/jobs/65555141/Ausbildung-als-Fachlagerist-m-w-d-,-Start-09-2027/", "https://jobs.loeffelhardt.de/"),
            "syntegon": ("https://jobs.syntegon.com/offer/hse-manager-m-w-d/1c3136a0-a713-41b7-9e23-b5789225c66e", "https://jobs.syntegon.com/search"),
        }
        for key, (ad, listing) in cases.items():
            with self.subTest(key=key):
                source = registry()[key]
                self.assertEqual(source.adapter, "sitemap")
                self.assertTrue(is_detail(ad, source))
                self.assertFalse(is_detail(listing, source))
