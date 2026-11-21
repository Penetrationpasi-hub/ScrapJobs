"""Stadt Waiblingen: all ads sit inline on the 3 MB list page of a site-builder career site."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
from safe_http import FetchError, MAX_BODY, MAX_LARGE_PAGE, Budget, Transport
from sources import registry
from waiblingen_adapter import postings

BASE = "https://karriere.waiblingen.de/"


def block(slug, title, body, link="Bewirb Dich jetzt!"):
    return (f'<div class="con-kit-molecule-textBlock"><div class="con-kit-component-atom-list">'
            f'<div data-atom="header"><h2>{title}</h2></div><div data-atom="text"><p>{body}</p></div>'
            f'<div class="con-kit-component-link-group"><a href="{BASE}{slug}">{link}</a></div></div></div>')


LONG = " Umfang: Vollzeit Start ab: sofort Entgeltgruppe: E 9 TVöD Wir bieten vielfältige Fort- und Weiterbildungsangebote und mehr. " * 2
PAGE = ("<html><head><style>.a{color:red}</style><script>var x = '<a href=\"" + BASE + "evil\">Bewirb</a>';</script></head><body>"
        + block("bewerbung-abwassermeister", "Abwassermeister (m/w/d)", "im Eigenbetrieb Stadtentwässerung." + LONG)
        + block("bewerbung-elektriker", "Elektriker (m/w/d)", "Bewirb Dich bitte bis zum 27.11.2026." + LONG, link="Bewerben Sie sich jetzt!")
        + block("bewerbung-alt", "Hausmeister (m/w/d)", "Bewirb Dich bitte bis zum 01.01.2020." + LONG)
        + block("impressum-stadt-waiblingen", "Servicelinks", "Datenschutz Impressum", link="Impressum")
        + '<div class="con-kit-molecule-textBlock"><div data-atom="header"><h2>Menü</h2></div>'
          f'<a href="{BASE}ausbildung">Ausbildungsberufe</a><a href="{BASE}studium">Studium</a></div>'
        + "</body></html>")


def text_atom(kind, text):
    return {"type": kind, "data": {"text": {"blocks": [{"key": "a", "text": text, "type": "unstyled"}], "entityMap": {}}}}


def state_molecule(slug, title, body, umfang="Umfang:"):
    return {"type": "molecule", "atoms": [
        {"type": "image", "data": {"src": "media/x"}}, text_atom("header", title), text_atom("plain-text", body),
        {"type": "menu-v2", "data": {"items": [{"data": {"link_text": umfang, "link_subtitle": "100 %"}}]}},
        {"type": "list", "data": {"items": [{"data": {"header_text": {"blocks": [{"text": "Was Dich erwartet"}]},
                                                      "plain_text": {"blocks": [{"text": "• Betrieb der Anlage und viele weitere Aufgaben"}]}}}]}},
        {"type": "link-group", "data": {"first_link_text": "Bewirb Dich jetzt!", "first_link_href": "/" + slug}},
        {"type": "contacts", "data": {"items": [{"data": {"type": "phone", "subtitle": "07151 5001 - 3500"}}]}}]}


def state_page(*molecules, extra=""):
    import json as _json
    state = {"_id": "x", "version": {"sections": [{"layer": {"frames": [{"rows": [{"molecules": list(molecules)}]}]}}]}}
    return ("<html><body><div id=\"app\"></div><script>" + _json.dumps(state) + "</script>" + extra + "</body></html>")


STATE = state_page(
    state_molecule("bewerbung-abwassermeister", "Abwassermeister (m/w/d)", "im Eigenbetrieb Stadtentwässerung. Bewirb Dich bitte bis zum 27.11.2026."),
    state_molecule("bewerbung-alt", "Hausmeister (m/w/d)", "Bewirb Dich bitte bis zum 01.01.2020."),
    state_molecule("alle-stellen", "Lust auf eine Aufgabe?", "Unsere Einsatzmöglichkeiten bei der Stadt Waiblingen und mehr.", umfang="Adresse:"),
    state_molecule("offene-stellen", "Offene Stellen", "Stellenliste", umfang="Umfang:"))


class Fake:
    fetched = []
    page = PAGE

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            return raw, "User-agent: *\nAllow: /\n"
        if authorize:
            authorize(raw)
        Fake.fetched.append((raw, kw))
        return raw, Fake.page


def run(q="", page=PAGE):
    Fake.fetched, Fake.page = [], page
    req = SimpleNamespace(q=q, location="", radius_km=25, sources=["stadt_waiblingen"])
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "stadt_waiblingen"}):
        return crawler.crawl(req, Fake)


class WaiblingenTest(unittest.TestCase):
    def test_reads_ad_blocks_not_scripts_or_navigation(self):
        rows = list(postings(PAGE))
        self.assertEqual([r[0].rsplit("/", 1)[1] for r in rows],
                         ["bewerbung-abwassermeister", "bewerbung-elektriker", "bewerbung-alt"])
        self.assertEqual(rows[1][3], "2026-11-27T23:59:59+01:00")

    def test_jobs_with_fixed_employer_and_place_and_expired_ones_dropped(self):
        result = run()
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(Fake.fetched[0][0], BASE + "offene-stellen")
        self.assertEqual(Fake.fetched[0][1], {"large_page": True})
        jobs = {j["title"]: j for j in result["jobs"]}
        self.assertEqual(sorted(jobs), ["Abwassermeister (m/w/d)", "Elektriker (m/w/d)"])
        self.assertIn("Abwassermeister (m/w/d)", jobs)
        self.assertNotIn("Hausmeister (m/w/d)", jobs)  # Frist 2020 abgelaufen
        first = jobs["Abwassermeister (m/w/d)"]
        self.assertEqual((first["company"], first["url"]), ("Stadt Waiblingen", BASE + "bewerbung-abwassermeister"))
        self.assertIn("Waiblingen", first["location"])

    def test_reads_the_json_state_when_the_html_has_no_rendered_blocks(self):
        rows = list(postings(STATE))
        self.assertEqual([r[0].rsplit("/", 1)[1] for r in rows], ["bewerbung-abwassermeister", "bewerbung-alt"])
        self.assertEqual(rows[0][1], "Abwassermeister (m/w/d)")
        self.assertIn("Umfang: 100 %", rows[0][2])
        self.assertIn("Was Dich erwartet", rows[0][2])
        self.assertNotIn("07151", rows[0][2])  # Ansprechpartner-Telefon nicht übernehmen
        self.assertEqual(rows[0][3], "2026-11-27T23:59:59+01:00")
        result = run(page=STATE)
        self.assertEqual([j["title"] for j in result["jobs"]], ["Abwassermeister (m/w/d)"])  # Hausmeister abgelaufen

    def test_search_term_filters(self):
        self.assertEqual([j["title"] for j in run("Abwasser")["jobs"]], ["Abwassermeister (m/w/d)"])

    def test_page_without_blocks_is_reported(self):
        result = run(page="<html><body>Hallo</body></html>")
        self.assertEqual(result["sources"][0]["status"], "unsupported")
        self.assertIn("keine Stellenblöcke", result["sources"][0]["detail"])
        self.assertIn("Zustand nein", result["sources"][0]["detail"])

    def test_registry_binding(self):
        source = registry()["stadt_waiblingen"]
        self.assertEqual((source.adapter, source.hosts), ("waiblingen_page", ("karriere.waiblingen.de",)))


class LargePageTransportTest(unittest.TestCase):
    def fetch(self, size, **options):
        class Response:
            status = 200

            def __init__(self):
                self.data = b"a" * size

            def getheader(self, name, default=None):
                return {"Content-Type": "text/html"}.get(name, default)

            def read(self, n=-1):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

        class Connection:
            def __init__(self, *a): pass
            def request(self, *a, **k): pass
            def getresponse(self): return Response()
            def close(self): pass

        transport = Transport(Budget(), resolve=lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))], connection=Connection)
        return transport.get("https://karriere.waiblingen.de/offene-stellen", ("karriere.waiblingen.de",), **options)[1]

    def test_default_limit_stays_two_mib_and_large_page_lifts_it(self):
        with self.assertRaises(FetchError) as caught:
            self.fetch(MAX_BODY + 1)
        self.assertEqual(caught.exception.code, "too_large")
        self.assertEqual(caught.exception.detail, "mehr als 2048 KB (Limit)")
        self.assertEqual(len(self.fetch(3 * 1024 * 1024 + 5, large_page=True)), 3 * 1024 * 1024 + 5)
        with self.assertRaises(FetchError) as caught:
            self.fetch(MAX_LARGE_PAGE + 1, large_page=True)
        self.assertEqual(caught.exception.detail, "mehr als 6144 KB (Limit)")

    def test_large_page_cannot_be_combined(self):
        for options in ({"accept_json": True}, {"accept_xml": True}, {"max_body": 3 * 1024 * 1024}, {"robots_request": True}):
            with self.assertRaises(FetchError):
                self.fetch(10, large_page=True, **options)


if __name__ == "__main__":
    unittest.main()
