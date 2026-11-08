"""Offline regressions for the three inspected public Helix portal formats."""
import json
import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from crawler import crawl
from extraction import discovery, extract, is_detail
from sources import registry


CASES = (
    ("ksk_waiblingen", "/ksk/jobad?prj=100052P643",
     "Finanzberatung, Digitales Beratungscenter", "Kreissparkasse Waiblingen", "Winnenden"),
    ("landratsamt_rmk", "/_/jobad?prj=100300P28",
     "Pflichtpraktikum", "Landratsamt Rems-Murr-Kreis", "Waiblingen"),
    ("volksbank_stuttgart", "/_/jobad?prj=100073P435",
     "Duales Studium 01.09.2027 - Bachelor of Arts (B.A.) BWL-Bank",
     "Volksbank Stuttgart eG", "Stuttgart"),
)


def document(company, title, town, **overrides):
    # Actual public metadata shape; short sample description, no copied full ad.
    data = {"@type": "JobPosting", "title": title,
            "hiringOrganization": {"@type": "Organization", "name": company},
            "jobLocation": {"@type": "Place", "address": {
                "@type": "PostalAddress", "addressLocality": town, "addressCountry": "DE"}},
            "description": "Beratung und Verwaltung im Team."}
    data.update(overrides)
    # Helix includes both WebSite and JobPosting scripts on the detail page.
    return ('<script type="application/ld+json">{"@type":"WebSite","name":"Karriere"}</script>'
            '<script type="application/ld+json">' + json.dumps(data) + "</script>")


class HelixPortals(unittest.TestCase):
    def test_actual_query_id_links_discovered_not_career_or_application_pages(self):
        for key, path, title, company, town in CASES:
            with self.subTest(source=key):
                source = registry()[key]
                root = "https://" + source.hosts[0]
                html = (f'<a href="{path}">{title}</a>'
                        '<a href="/ksk/career">Karriere</a>'
                        '<a href="/_/joblist">Alle Stellen</a>'
                        '<a href="/_/apply?prj=100300P28">Bewerben</a>'
                        f'<a href="https://evil.test{path}">Andere Website</a>')
                links, following = discovery(html, source.start("Beratung", ""), source, "Beratung")
                self.assertEqual(links, [root + path])
                self.assertIsNone(following)
                self.assertTrue(source.search.endswith("/joblist"))
                self.assertFalse(is_detail(source.search, source))
                for bad in (path.split("?")[0], path.replace("prj=", "id="),
                            re.sub(r"prj=\d+P", "prj=999999P", path),
                            path + "&redirect=https://evil.test"):
                    self.assertFalse(is_detail(root + bad, source), bad)

    def test_volksbank_does_not_use_empty_old_career_subportal(self):
        source = registry()["volksbank_stuttgart"]
        root = "https://" + source.hosts[0]
        self.assertEqual(source.search, root + "/_/joblist")
        self.assertFalse(is_detail(root + "/tvbvbs/jobad?prj=100073P435", source))
        self.assertFalse(is_detail(root + "/tvbvbs/career", source))
        self.assertEqual(discovery('<p>Keine Ergebnisse gefunden.</p>',
                                   root + "/tvbvbs/joblist", source), ([], None))

    def test_metadata_comes_from_single_jobposting_with_exact_employer(self):
        for key, path, title, company, town in CASES:
            with self.subTest(source=key):
                source = registry()[key]
                raw = "https://" + source.hosts[0] + path
                job = extract(document(company, title, town), raw, source, "Beratung")
                self.assertEqual(job["title"], title)
                self.assertEqual(job["company"], company)
                self.assertIn(town, job["location"])
                self.assertEqual(job["url"], raw)
                self.assertIsNone(extract(document("Fremder Arbeitgeber", title, town), raw, source))
                self.assertIsNone(extract(document(company, "Initiativbewerbung", town), raw, source))
                self.assertIsNone(extract(document(company, title, town, validThrough="2020-01-01"), raw, source))
                self.assertIsNone(extract(document(company, title, town), raw, source, "UnpassenderSuchbegriff"))
                self.assertIsNone(extract('<h1>' + title + "</h1>", raw, source))

    def test_worker_follows_three_lists_checks_robots_and_emits_verified_details(self):
        fixtures = {}
        for key, path, title, company, town in CASES:
            source = registry()[key]
            fixtures[source.search] = f'<a href="{path}">{title}</a>'
            fixtures["https://" + source.hosts[0] + path] = document(company, title, town)
        requested = []
        class FixtureTransport:
            def __init__(self, budget):
                self.budget, self.last = budget, {}
            def get(self, raw, hosts, authorize=None, **options):
                if authorize:
                    authorize(raw)
                self.budget.claim()
                requested.append(raw)
                if urlsplit(raw).path == "/robots.txt":
                    return raw, "User-agent: *\nAllow: /"
                return raw, fixtures[raw]
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": ",".join(case[0] for case in CASES)}):
            result = crawl(SimpleNamespace(q="Beratung", location="Waiblingen",
                                          sources=[case[0] for case in CASES]), FixtureTransport)
        self.assertEqual(len(result["jobs"]), 3)
        self.assertEqual(result["documents"], 9)
        self.assertEqual([row["status"] for row in result["sources"]], ["done"] * 3)
        self.assertEqual([row["kept"] for row in result["sources"]], [1] * 3)
        self.assertEqual(sum(url.endswith("/robots.txt") for url in requested), 3)
