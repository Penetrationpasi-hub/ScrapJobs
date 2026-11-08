"""Offline checks for the Murrelektronik reader; synthetic pages in the observed format."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crawler import crawl
from murr_adapter import murr
from robots_exceptions import missing_robots_scope
from safe_http import FetchError
from sources import registry

BASE = "https://www.murrelektronik.com"
LIST = BASE + "/de/landingpages/karriere/stellenangebote/"
PATH = "/de/landingpages/karriere/stellenangebote/detail/job/"
TEXT = ("Ihre Aufgaben: Fehlersuche, Wartung und Dokumentation an Anlagen der Automatisierungstechnik. "
        "Ihre Qualifikationen: Berufsausbildung in Mechatronik, Elektronik oder Mechanik.")


def listing(*slugs):
    return "<html><body>" + "".join(f'<a href="{PATH}{slug}/">x</a>' for slug in slugs) + "</body></html>"


def detail(title="Mechatroniker (m/w/d)", employer="Murrelektronik GmbH", body=TEXT, meta=None, h1=1):
    org = json.dumps({"@context": "https://schema.org", "@type": "Corporation", "name": employer})
    meta = meta if meta is not None else f"Zur Unterstützung unseres Teams an unserem Standort in Stollberg/Erzgebirge suchen wir Sie! {title}"
    return (f'<html><head><meta name="description" content="{meta}">'
            f'<script type="application/ld+json">{org}</script></head><body>'
            + f'<div class="contentElementContainer">' + f'<h1 class="leadHeadline">{title}</h1>' * h1
            + f'<p>{body}</p></div></body></html>')


class Murrelektronik(unittest.TestCase):
    def setUp(self):
        self.source = registry()["murrelektronik"]
        self.req = SimpleNamespace(q="Mechatroniker", location="", sources=["murrelektronik"])
        self.report = {"filtered": 0}

    def run_adapter(self, pages):
        def get(raw, source, **options):
            self.assertEqual(options, {})
            value = pages[raw]
            if isinstance(value, FetchError):
                raise value
            return raw, value
        return list(murr(self.source, self.req, get, self.report))

    def test_source_is_enabled_and_bound(self):
        self.assertTrue(self.source.available)
        self.assertEqual(self.source.adapter, "murr")
        self.assertEqual(self.source.hosts, ("www.murrelektronik.com",))

    def test_verified_vacancy_uses_page_title_employer_and_documented_location(self):
        url = BASE + PATH + "mechatroniker-m-w-d"
        jobs = self.run_adapter({LIST: listing("mechatroniker-m-w-d", "initiativbewerbung"), url: detail(),
                                 BASE + PATH + "initiativbewerbung": detail("Initiativbewerbung")})
        self.assertEqual([j["title"] for j in jobs], ["Mechatroniker (m/w/d)"])
        self.assertEqual(jobs[0]["company"], "Murrelektronik GmbH")
        self.assertEqual(jobs[0]["location"], "Stollberg")
        self.assertEqual(jobs[0]["url"], url)
        self.assertEqual(self.report["filtered"], 1)

    def test_no_location_is_invented_and_foreign_or_missing_employer_is_dropped(self):
        a, b, c = (BASE + PATH + s for s in ("a-mechatroniker", "b-mechatroniker", "c-mechatroniker"))
        jobs = self.run_adapter({
            LIST: listing("a-mechatroniker", "b-mechatroniker", "c-mechatroniker"),
            a: detail(meta="Mechatroniker (m/w/d)"),
            b: detail(employer="Andere Firma GmbH"),
            c: detail(h1=2)})
        self.assertEqual([j["location"] for j in jobs], [""])
        self.assertEqual(self.report["filtered"], 2)

    def test_short_expired_and_non_matching_pages_are_dropped(self):
        a, b, c = (BASE + PATH + s for s in ("a-mechatroniker", "b-mechatroniker", "c-mechatroniker"))
        jobs = self.run_adapter({
            LIST: listing("a-mechatroniker", "b-mechatroniker", "c-mechatroniker"),
            a: detail(body="Zu kurz."),
            b: detail(body=TEXT + " Diese Stelle ist bereits besetzt."),
            c: detail(title="Buchhalter (m/w/d)", body="Buchhaltung " * 20)})
        self.assertEqual(jobs, [])
        self.assertEqual(self.report["filtered"], 3)

    def test_removed_detail_is_filtered_and_other_errors_propagate(self):
        a, b = BASE + PATH + "a-mechatroniker", BASE + PATH + "b-mechatroniker"
        self.assertEqual(self.run_adapter({LIST: listing("a-mechatroniker", "b-mechatroniker"),
                                           a: FetchError("gone", http_status=404), b: detail()})[0]["url"], b)
        with self.assertRaises(FetchError):
            self.run_adapter({LIST: listing("a-mechatroniker"), a: FetchError("blocked")})

    def test_empty_list_is_unsupported_not_zero_vacancies(self):
        self.assertEqual(self.run_adapter({LIST: "<html><body>Kein Link</body></html>"}), [])
        self.assertEqual(self.report["status"], "unsupported")

    def test_foreign_or_non_detail_links_are_not_followed(self):
        html = ('<a href="https://evil.test' + PATH + 'x/">x</a><a href="/de/kontakt/">k</a>'
                '<a href="' + PATH + 'x/?next=https://evil.test">q</a>')
        self.assertEqual(self.run_adapter({LIST: html}), [])

    def test_robots_exception_covers_only_exact_get_routes(self):
        s = self.source
        self.assertTrue(missing_robots_scope(LIST, s, {}))
        self.assertTrue(missing_robots_scope(BASE + PATH + "mechatroniker-m-w-d/", s, {}))
        for url in [BASE + "/", BASE + "/de/", BASE + PATH, BASE + PATH + "a/b/",
                    LIST + "?q=x", LIST + "#x", "https://my.murrelektronik.com" + PATH + "a/",
                    "https://evil.test" + PATH + "a/", BASE + ":443" + PATH + "a/",
                    "http://www.murrelektronik.com" + PATH + "a/"]:
            self.assertFalse(missing_robots_scope(url, s, {}), url)
        self.assertFalse(missing_robots_scope(LIST, s, {"json_body": {}}))
        self.assertFalse(missing_robots_scope(LIST, s, {"accept_json": True}))
        self.assertFalse(missing_robots_scope(LIST, registry()["judo"], {}))

    def test_crawler_only_known_missing_robots_answers_are_tolerated(self):
        for status in [301, 404, 410, 403, 429, 500, "User-agent: *\nDisallow: /", "<html>Home</html>"]:
            reads = []

            def factory(budget, status=status, reads=reads):
                class Fixture:
                    last = {}

                    def get(self, raw, hosts, authorize=None, **options):
                        if authorize:
                            authorize(raw)
                        budget.claim()
                        if raw.endswith("/robots.txt"):
                            assert options == {"robots_request": True}
                            if isinstance(status, int):
                                raise FetchError("unsupported" if status == 301 else "gone", http_status=status)
                            return raw, status
                        reads.append(raw)
                        return raw, listing()
                return Fixture()
            with self.subTest(status=status), patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "murrelektronik"}):
                result = crawl(SimpleNamespace(q="Mechatroniker", location="", sources=["murrelektronik"]), factory)
            tolerated = status in (301, 404)
            self.assertEqual(reads, [LIST] if tolerated else [])
            self.assertEqual(result["sources"][0]["status"], "unsupported" if tolerated else
                             "robots_denied" if "Disallow" in str(status) else "robots_unavailable")

    def test_other_sources_do_not_tolerate_a_robots_redirect(self):
        from robots_exceptions import missing_robots_statuses
        for key, source in registry().items():
            self.assertEqual(missing_robots_statuses(source), {404, 301} if key == "murrelektronik" else {404})


if __name__ == "__main__":
    unittest.main()
