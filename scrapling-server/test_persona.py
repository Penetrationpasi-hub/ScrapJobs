"""persona service: sitemap reader. Fixtures mirror the observed public sitemap-de.xml and job pages."""
import json
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

import crawler
import geo
from persona_adapter import MAX_SITEMAP, entries, select
from safe_http import Budget, FetchError, Transport
from sources import approved_sources, registry

SITEMAP_URL = "https://www.persona.de/sitemap-de.xml"
UUIDS = {name: f"{i:08x}-0000-4000-8000-{i:012x}" for i, name in enumerate(
    ["fuessen", "waiblingen", "stuttgart", "balingen", "unknown", "nogender", "english", "intern"], start=1)}
BASE = "https://www.persona.de"
PATHS = {
    "fuessen": "/jobs/elektroniker-m-w-d-fuessen/",
    "waiblingen": "/jobs/elektroinstallateur-m-w-d-waiblingen/",
    "stuttgart": "/jobs/elektroniker-betriebstechnik-m-w-d-stuttgart/",
    "balingen": "/jobs/mechatroniker-m-w-d-balingen/",
    "unknown": "/jobs/elektroniker-helfer-m-w-d-buehlingen/",
    "nogender": "/jobs/elektroniker-ausbildung/",
}
STAMPS = {"fuessen": "2026-11-09T07:01:01Z", "waiblingen": "2026-10-14T07:01:01Z", "stuttgart": "2026-11-01T07:01:01Z",
          "balingen": "2026-11-05T07:01:01Z", "unknown": "2026-11-08T07:01:01Z", "nogender": "2026-11-08T07:01:01Z"}


def url(name):
    return f"{BASE}{PATHS[name]}{UUIDS[name]}"


def block(loc, stamp="2026-11-09T07:01:01Z"):
    return (f'<url><loc>{loc}</loc><xhtml:link rel="alternate" hreflang="en-GB" href="{loc}"/>'
            f"<lastmod>{stamp}</lastmod><changefreq>monthly</changefreq></url>")


SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + block(BASE + "/") + block(BASE + "/jobs")
           + "".join(block(url(name), STAMPS[name]) for name in PATHS)
           + block(f"{BASE}/en-gb/jobs/electronics-technician-m-f-d-fuessen/{UUIDS['english']}")
           + block(f"{BASE}/interne-karriere/jobs/elektroniker-m-w-d-giessen/{UUIDS['intern']}")
           + "</urlset>")


def posting(title, city, postal, **changes):
    row = {"@context": "https://schema.org", "@type": "JobPosting", "title": title, "datePosted": "2026-11-09",
           "description": "du installierst elektrische Komponenten und Verdrahtungen an Maschinen und Baugruppen",
           "directApply": True, "employmentType": "FULL_TIME",
           "hiringOrganization": {"@type": "Organization", "name": "persona service AG & Co. KG", "sameAs": "https://persona.de"},
           "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": "DE", "addressLocality": city,
                                                         "addressRegion": "BY", "postalCode": postal}}}
    row.update(changes)
    return '<html><head><script type="application/ld+json">' + json.dumps(row) + "</script></head><body></body></html>"


DETAILS = {
    url("fuessen"): posting("Elektroniker (m/w/d)", "Füssen", "87642"),
    url("waiblingen"): posting("Elektroinstallateur (m/w/d)", "Waiblingen", "71332", validThrough="2099-01-01"),
    url("stuttgart"): posting("Elektroniker Betriebstechnik (m/w/d)", "Stuttgart", "70173"),
    url("unknown"): posting("Elektroniker Helfer (m/w/d)", "Bühlingen", "78234"),
    url("nogender"): posting("Elektroniker Ausbildung", "Ulm", "89073"),
}
ROBOTS = "User-agent: *\nDisallow: /healthz\nDisallow: /admin\nDisallow: /auth\nDisallow: /candidates\n\nSitemap: https://www.persona.de/sitemap-index.xml\n"


class Fake:
    fetched = []
    options = []

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            return raw, ROBOTS
        if authorize:
            authorize(raw)
        Fake.fetched.append(raw)
        Fake.options.append(kw)
        if raw == SITEMAP_URL:
            return raw, SITEMAP
        if raw in DETAILS:
            return raw, DETAILS[raw]
        raise FetchError("gone", http_status=404)


def run(q="Elektro", location="", radius_km=50, **extra):
    Fake.fetched, Fake.options = [], []
    req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=["persona"], **extra)
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "persona"}):
        return crawler.crawl(req, Fake)


class PersonaTest(unittest.TestCase):
    def test_sitemap_entries_split_title_and_place_and_skip_other_areas(self):
        rows = entries(SITEMAP)
        self.assertEqual(len(rows), 6)  # no home page, no /jobs list, no en-gb, no interne-karriere
        by_url = {row[2]: row for row in rows}
        title, place, _, stamp = by_url[url("fuessen")]
        self.assertEqual((title, place, stamp), ("elektroniker", "fuessen", STAMPS["fuessen"]))
        self.assertEqual(by_url[url("nogender")][:2], ("elektroniker-ausbildung", ""))
        self.assertEqual(by_url[url("stuttgart")][:2], ("elektroniker-betriebstechnik", "stuttgart"))

    def test_a_document_that_is_not_a_sitemap_is_reported(self):
        with self.assertRaises(FetchError) as caught:
            entries("<html><body>Nicht gefunden</body></html>")
        self.assertEqual(caught.exception.code, "unsupported")

    def test_selection_by_title_term_then_known_distance_then_unknown_place(self):
        origin = geo.center("Waiblingen")
        chosen = select(entries(SITEMAP), "Elektro", origin, 50)
        # Füssen is far away and dropped; Balingen has no matching term; the unresolvable village stays, last.
        self.assertNotIn(url("fuessen"), chosen)
        self.assertNotIn(url("balingen"), chosen)
        self.assertEqual(chosen[:2], [url("waiblingen"), url("stuttgart")])
        self.assertEqual(set(chosen[2:]), {url("nogender"), url("unknown")})

    def test_without_a_place_everything_matching_is_kept_newest_first(self):
        chosen = select(entries(SITEMAP), "Elektro", None, 50)
        self.assertEqual(chosen[0], url("fuessen"))
        self.assertEqual(len(chosen), 5)

    def test_every_search_term_counts_towards_the_ranking(self):
        chosen = select(entries(SITEMAP), "Elektroniker Betriebstechnik", None, 50)
        self.assertEqual(chosen[0], url("stuttgart"))

    def test_crawl_reads_sitemap_once_and_only_the_selected_details(self):
        result = run(location="Waiblingen")
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(Fake.fetched[0], SITEMAP_URL)
        self.assertEqual(Fake.options[0], {"accept_xml": True, "max_body": MAX_SITEMAP})
        self.assertNotIn(url("fuessen"), Fake.fetched)
        self.assertNotIn(url("balingen"), Fake.fetched)
        self.assertEqual(len(Fake.fetched), 1 + 4)
        jobs = {job["url"]: job for job in result["jobs"]}
        self.assertEqual(set(jobs), {url("waiblingen"), url("stuttgart"), url("nogender"), url("unknown")})
        job = jobs[url("waiblingen")]
        self.assertEqual((job["company"], job["title"]), ("persona service AG & Co. KG", "Elektroinstallateur (m/w/d)"))
        self.assertIn("71332 Waiblingen", job["location"])
        self.assertEqual(result["sources"][0]["detail"], "6 Anzeigen im Sitemap, 4 passend")

    def test_detail_budget_follows_the_source_limit(self):
        many = "".join(block(f"{BASE}/jobs/elektroinstallateur-m-w-d-waiblingen/{i:08x}-0000-4000-8000-{i:012x}") for i in range(10, 50))
        sitemap = SITEMAP.replace("</urlset>", many + "</urlset>")
        with mock.patch.object(Fake, "get", autospec=True,
                               side_effect=lambda self, raw, hosts, authorize=None, **kw: (raw, sitemap) if raw == SITEMAP_URL
                               else (raw, ROBOTS) if raw.endswith("/robots.txt") else (raw, DETAILS.get(raw, posting("Elektroinstallateur (m/w/d)", "Waiblingen", "71332")))):
            req = SimpleNamespace(q="Elektro", location="Waiblingen", radius_km=25, sources=["persona"])
            with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "persona"}):
                result = crawler.crawl(req, Fake)
        self.assertEqual(len(result["jobs"]), registry()["persona"].max_details)

    def test_expired_and_irrelevant_ads_are_dropped(self):
        DETAILS[url("waiblingen")] = posting("Elektroinstallateur (m/w/d)", "Waiblingen", "71332", validThrough="2020-01-01")
        try:
            result = run(location="Waiblingen")
        finally:
            DETAILS[url("waiblingen")] = posting("Elektroinstallateur (m/w/d)", "Waiblingen", "71332", validThrough="2099-01-01")
        self.assertNotIn(url("waiblingen"), {job["url"] for job in result["jobs"]})
        self.assertGreaterEqual(result["sources"][0]["filtered"], 1)

    def test_registry_binding_and_approval(self):
        source = registry()["persona"]
        self.assertEqual((source.adapter, source.api, source.hosts), ("persona_sitemap", SITEMAP_URL, ("www.persona.de",)))
        with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            self.assertIn("persona", approved_sources())

    def test_reader_cannot_be_pointed_at_another_feed(self):
        source = registry()["persona"]
        with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([{
                "key": "evil", "label": "x", "hosts": list(source.hosts), "search": "https://www.persona.de/jobs",
                "detail": "^/jobs/.+$", "adapter": "persona_sitemap", "api": "https://www.persona.de/other.xml"}])}):
            with self.assertRaises(ValueError):
                registry()


class LargeXmlTransportTest(unittest.TestCase):
    def fetch(self, size, **options):
        body = b"<urlset>" + b"x" * size + b"</urlset>"

        class Response:
            status = 200

            def __init__(self):
                self.data = body

            def getheader(self, name, default=None):
                return {"Content-Type": "application/xml; charset=utf-8"}.get(name, default)

            def read(self, n=-1):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

        class Connection:
            def __init__(self, *a): pass
            def request(self, *a, **k): pass
            def getresponse(self): return Response()
            def close(self): pass

        transport = Transport(Budget(), resolve=lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))], connection=Connection)
        return transport.get(SITEMAP_URL, ("www.persona.de",), accept_xml=True, **options)[1]

    def test_four_megabytes_need_the_explicit_xml_limit(self):
        size = 4 * 1024 * 1024
        with self.assertRaises(FetchError) as caught:
            self.fetch(size)
        self.assertEqual(caught.exception.code, "too_large")
        self.assertGreater(len(self.fetch(size, max_body=MAX_SITEMAP)), size)

    def test_the_limit_stays_bounded_and_xml_only(self):
        with self.assertRaises(FetchError) as caught:
            self.fetch(10, max_body=9 * 1024 * 1024)
        self.assertEqual(caught.exception.code, "unsupported")
        with self.assertRaises(FetchError) as caught:
            self.fetch(10, max_body=1024)
        self.assertEqual(caught.exception.code, "unsupported")
        with self.assertRaises(FetchError) as caught:
            Transport(Budget()).get("https://www.persona.de/jobs", ("www.persona.de",), max_body=MAX_SITEMAP)
        self.assertEqual(caught.exception.code, "unsupported")
        with self.assertRaises(FetchError):
            self.fetch(5 * 1024 * 1024 + 1, max_body=5 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
