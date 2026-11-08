import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from regional_additions import harro, harro_records, judo
from safe_http import FetchError
from sources import registry


def flight(rows):
    payload = '1:["$",null,{"jobs":' + json.dumps(rows) + '}]'
    # The real portal splits server data across multiple script chunks.
    middle = len(payload) // 2
    return "".join("<script>self.__next_f.push(" + json.dumps([1, chunk]) + ")</script>"
                   for chunk in [payload[:middle], payload[middle:]])


class RegionalAdditionsTest(unittest.TestCase):
    def setUp(self):
        self.sources = registry()
        self.req = SimpleNamespace(q="Meister", location="Backnang", radius=25)
        self.report = {"filtered": 0, "status": "done"}

    def test_judo_actual_filter_get_and_job_location_not_postal_contact(self):
        source = self.sources["judo"]
        calls = []
        url = "https://judo.eu/Stellenanzeige/logistikmeister-m-w-d/"

        def get(raw, configured, **options):
            self.assertIs(configured, source)
            self.assertNotIn("json_body", options)
            calls.append(raw)
            if raw == source.search:
                return raw, '<form id="filter-all" action="' + source.api + '"><input name="custom_stellenanzeigen_nonce" value="0123456789"></form>'
            if raw.startswith(source.api + "?"):
                self.assertIn("action=jobfilter", raw)
                self.assertIn("custom_stellenanzeigen_nonce=0123456789", raw)
                return raw, json.dumps({"success": True, "data": '<a href="' + url + '">Logistikmeister</a>'})
            return raw, """<div class="container wrapper"><div class="row"><div class="col-md-12">
            <h3 class="wp-block-heading">Logistikmeister (m/w/d)</h3>
            <p>Die JUDO Wasseraufbereitung GmbH sucht an unserem Standort in Backnang-Waldrems einen
            Logistikmeister. Sie übernehmen die Planung der Lagerabläufe und unterstützen
            die Mitarbeitenden bei der Organisation und Sicherstellung der Warenverfügbarkeit.</p>
            </div></div></div><footer>Postanschrift: Winnenden</footer>"""

        jobs = list(judo(source, self.req, get, self.report))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "Backnang-Waldrems")
        self.assertEqual(jobs[0]["company"], "JUDO Wasseraufbereitung GmbH")
        self.assertEqual(jobs[0]["url"], url.rstrip("/"))

    def test_judo_rejects_foreign_action_or_missing_nonce_without_api_request(self):
        source = self.sources["judo"]
        for html in ['<form id="filter-all" action="https://evil.test/"></form>',
                     '<form id="filter-all" action="' + source.api + '"></form>']:
            calls = []
            def get(raw, *_args, **_options):
                calls.append(raw)
                return raw, html
            with self.assertRaises(FetchError):
                list(judo(source, self.req, get, self.report))
            self.assertEqual(calls, [source.search])

    def test_harro_split_server_data_is_parsed_without_js_execution(self):
        row = {"jobId": "726-de_DE", "locale": "de", "title": "Meister"}
        self.assertEqual(harro_records(flight([row])), [row])
        with self.assertRaises(FetchError):
            harro_records('<script>self.__next_f.push(eval("dangerous"))</script>')
        with self.assertRaises(FetchError):
            harro_records("<html>0 Stellenangebote</html>")

    def test_harro_requires_exact_employer_title_and_detail_not_search_page(self):
        source = self.sources["harro_hoefliger"]
        url = source.search + "/meister-produktion"
        row = {"jobId": "726-de_DE", "locale": "de", "title": "Meister Produktion", "link": url}
        invalid = [{"jobId": "1-de_DE", "locale": "de", "title": "Meister", "link": source.search},
                   {**row, "link": "https://evil.test/karriere/stellenangebote/meister"},
                   {**row, "locale": "en"}, {**row, "link": None}]
        for company, title, expected in [
            ("Harro Höfliger Verpackungsmaschinen GmbH", row["title"], 1),
            ("Fremde Firma", row["title"], 0),
            ("Harro Höfliger Verpackungsmaschinen GmbH", "Andere Stelle", 0),
        ]:
            calls = []
            def get(raw, *_args, **_options):
                calls.append(raw)
                if raw == source.search:
                    return raw, flight([*invalid, row, row])
                return raw, '<script type="application/ld+json">' + json.dumps({
                    "@type": "JobPosting", "title": title, "hiringOrganization": {"name": company},
                    "description": "Meister für die Produktion und Qualitätssicherung",
                    "jobLocation": {"address": {"addressLocality": "Allmersbach im Tal", "addressCountry": "DE"}}
                }) + "</script>"
            jobs = list(harro(source, self.req, get, self.report))
            self.assertEqual(len(jobs), expected)
            self.assertEqual(calls, [source.search, url])

    def test_harro_no_jobs_and_fetch_failure_are_distinct(self):
        source = self.sources["harro_hoefliger"]
        self.assertEqual(list(harro(source, self.req, lambda raw, *_: (raw, flight([])), self.report)), [])
        self.assertEqual(self.report["status"], "no_matches")
        def blocked(*_args, **_options):
            raise FetchError("robots_unavailable")
        with self.assertRaises(FetchError):
            list(harro(source, self.req, blocked, self.report))

    def test_new_source_does_not_borrow_burger_schloz_robots_exception(self):
        from carsonal_adapter import missing_robots_scope
        source = self.sources["harro_hoefliger"]
        self.assertFalse(missing_robots_scope(source.search, source, {}))

    def test_harro_exception_only_covers_exact_get_job_routes(self):
        from robots_exceptions import missing_robots_scope
        source = self.sources["harro_hoefliger"]
        self.assertTrue(missing_robots_scope(source.search, source, {}))
        self.assertTrue(missing_robots_scope(source.search + "/meister-produktion", source, {}))
        for url in ["https://hoefliger.com/", "https://hoefliger.com/api/jobs",
                    "https://evil.test/karriere/stellenangebote",
                    source.search + "?url=https://evil.test", source.search + "/x/y",
                    source.search + "#other", "https://hoefliger.com:443/karriere/stellenangebote"]:
            self.assertFalse(missing_robots_scope(url, source, {}), url)
        self.assertFalse(missing_robots_scope(source.search, source, {"json_body": {}}))
        self.assertFalse(missing_robots_scope(source.search, self.sources["judo"], {}))

    def test_socco_only_official_tenant_details_and_verified_company(self):
        from extraction import discovery, extract
        source = self.sources["socco"]
        raw = "https://k57824.coveto.de/job-meister-backnang-12345.html"
        links, _ = discovery('<a href="' + raw + '">Meister</a><a href="https://other.coveto.de/job-meister-12345.html">Meister</a>'
                             '<a href="https://k57824.coveto.de/public/bewerbung">Bewerben</a>', source.start("Meister", "Backnang"), source, "Meister")
        self.assertEqual(links, [raw])
        row = {"@type": "JobPosting", "title": "Meister (m/w/d)",
               "hiringOrganization": {"name": "SOCCO GROUP GmbH"},
               "jobLocation": {"address": {"addressLocality": "Backnang", "addressCountry": "DE"}},
               "description": "Meister für die Produktion"}
        def html():
            return '<script type="application/ld+json">' + json.dumps(row) + "</script>"
        job = extract(html(), raw, source, "Meister")
        self.assertEqual(job["location"], "Backnang DE")
        row["hiringOrganization"]["name"] = "Andere Firma"
        self.assertIsNone(extract(html(), raw, source, "Meister"))

    def test_harro_crawler_only_direct_404_can_bypass_missing_robots(self):
        from crawler import crawl
        source = self.sources["harro_hoefliger"]
        req = SimpleNamespace(q="Meister", location="", sources=[source.key])
        for status in [404, 410, 403, 429, 500, "User-agent: *\nDisallow: /", "<html>Error</html>"]:
            reads = []
            def factory(budget):
                class Fixture:
                    last = {}
                    def get(self, raw, hosts, authorize=None, **options):
                        if authorize:
                            authorize(raw)
                        budget.claim()
                        if raw.endswith("/robots.txt"):
                            self_test.assertEqual(options, {"robots_request": True})
                            if isinstance(status, int):
                                raise FetchError("gone", http_status=status)
                            return raw, status
                        reads.append(raw)
                        return raw, flight([])
                return Fixture()
            self_test = self
            with self.subTest(status=status), patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": source.key}):
                result = crawl(req, factory)
            self.assertEqual(reads, [source.search] if status == 404 else [])
            self.assertEqual(result["sources"][0]["status"],
                             "no_matches" if status == 404 else "robots_denied" if "Disallow" in str(status) else "robots_unavailable")


if __name__ == "__main__":
    unittest.main()
