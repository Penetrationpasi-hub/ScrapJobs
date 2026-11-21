"""Lidl (jobs.lidl.de): sitemap reader. Fixtures mirror the observed sitemap-jobs.xml and a real job page."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
import geo
from lidl_adapter import MAX_SITEMAP, entries, select
from safe_http import FetchError
from sources import registry

SITEMAP_URL = "https://jobs.lidl.de/sitemap-jobs.xml"
BASE = "https://jobs.lidl.de/jobs/"
SLUGS = {
    "waiblingen": "verkaeufer-teilzeit-m-w-d-waiblingen-761201",
    "fellbach": "verkaeufer-mit-stellvertretung-teilzeit-m-w-d-fellbach-761300",
    "hamburg": "verkaeufer-teilzeit-m-w-d-hamburg-761400",
    "allgaeu": "verkaeufer-mit-stellvertretung-m-w-d-kempten-allgaeu-757574",
    "unknown": "verkaeufer-m-w-d-xyzdorf-761500",
    "filialleiter": "stellvertretender-filialleiter-m-w-d-waiblingen-749562",
    "praktikum": "praktikum-controlling-international-sap-bi-reporting-neckarsulm-771819",
    "dots": "mitarbeiter-warenverraeumung-9-14-std.-woche-teilzeit-m-w-d-rendsburg-746146",
}
STAMPS = {name: f"2026-11-{10 + i:02d}T14:37:50+00:00" for i, name in enumerate(SLUGS)}


def block(loc, stamp="2026-11-18T14:37:50+00:00"):
    return f"<url><loc>{loc}</loc><lastmod>{stamp}</lastmod></url>"


SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="https://www.w3.org/1999/xhtml">' + "".join(block(BASE + slug, STAMPS[name]) for name, slug in SLUGS.items())
           + block("https://jobs.lidl.de/lidl-als-arbeitgeber/vorteile") + block(BASE + "ohne-id-m-w-d-berlin") + "</urlset>")


def posting(title, city, postal, lat, lon, **changes):
    row = {"@context": "https://schema.org", "@type": "JobPosting", "datePosted": "2026-11-18T14:36:18+00:00",
           "description": "<div><h2>Einleitung</h2><p>Du verkaufst in unserer Filiale Waren und betreust Kunden freundlich.</p></div>",
           "hiringOrganization": {"@type": "Organization", "name": "Lidl Vertriebs-GmbH & Co. KG, Erlensee Süd"},
           "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "streetAddress": "Am Güßgraben 2",
                                                         "postalCode": postal, "addressLocality": city, "addressCountry": "DE"},
                           "geo": {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}},
           "title": title, "identifier": {"@type": "PropertyValue", "value": "761201"}}
    row.update(changes)
    return '<html><head><script type="application/ld+json">' + json.dumps(row) + "</script></head><body></body></html>"


DETAILS = {
    BASE + SLUGS["waiblingen"]: posting("Verkäufer Teilzeit (m/w/d)", "Waiblingen", "71332", 48.83, 9.32),
    BASE + SLUGS["fellbach"]: posting("Verkäufer mit Stellvertretung Teilzeit (m/w/d)", "Fellbach", "70734", 48.81, 9.27),
    BASE + SLUGS["unknown"]: posting("Verkäufer (m/w/d)", "Xyzdorf", "88888", 48.0, 9.0),
}
ROBOTS = "User-agent: *\nDisallow: /cps/\n\nSitemap: https://jobs.lidl.de/sitemap.xml"


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


def run(q="Verkäufer", location="", radius_km=25):
    Fake.fetched, Fake.options = [], []
    req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=["lidl"])
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "lidl"}):
        return crawler.crawl(req, Fake)


class LidlTest(unittest.TestCase):
    def test_sitemap_entries_split_title_place_and_id(self):
        rows = {row[2]: row for row in entries(SITEMAP)}
        self.assertEqual(len(rows), len(SLUGS))  # weder Inhaltsseiten noch URLs ohne Anzeigen-ID
        title, place, _, stamp = rows[BASE + SLUGS["fellbach"]]
        self.assertEqual((title, place), ("verkaeufer-mit-stellvertretung-teilzeit", "fellbach"))
        self.assertEqual(rows[BASE + SLUGS["allgaeu"]][:2], ("verkaeufer-mit-stellvertretung", "kempten-allgaeu"))
        self.assertEqual(rows[BASE + SLUGS["praktikum"]][1], "")  # kein Geschlechtsmarker
        self.assertTrue(rows[BASE + SLUGS["dots"]][0].endswith("std.-woche-teilzeit"))  # Punkte im Titel
        self.assertEqual(rows[BASE + SLUGS["fellbach"]][3], STAMPS["fellbach"])

    def test_a_document_that_is_not_a_sitemap_is_reported(self):
        with self.assertRaises(FetchError) as caught:
            entries("<html><body>Nicht gefunden</body></html>")
        self.assertEqual(caught.exception.code, "unsupported")

    def test_selection_by_title_then_distance_then_unknown_place(self):
        origin = geo.center("Waiblingen")
        chosen = select(entries(SITEMAP), "Verkäufer", origin, 25)
        self.assertEqual(chosen[:2], [BASE + SLUGS["waiblingen"], BASE + SLUGS["fellbach"]])
        self.assertNotIn(BASE + SLUGS["hamburg"], chosen)
        self.assertNotIn(BASE + SLUGS["allgaeu"], chosen)  # Kempten liegt weit weg (mehrwortiger Ort)
        self.assertNotIn(BASE + SLUGS["filialleiter"], chosen)  # Titelwort fehlt
        self.assertEqual(chosen[2], BASE + SLUGS["unknown"])  # unbekannter Ort steht hinten, bleibt aber dabei

    def test_place_at_the_end_of_a_title_without_gender_marker(self):
        origin = geo.center("Waiblingen")
        self.assertEqual(select(entries(SITEMAP), "Praktikum", origin, 60), [BASE + SLUGS["praktikum"]])  # Neckarsulm ~39 km
        self.assertEqual(select(entries(SITEMAP), "Praktikum", origin, 10), [])

    def test_without_a_place_everything_matching_is_kept_newest_first(self):
        chosen = select(entries(SITEMAP), "Verkäufer", None, 25)
        self.assertEqual(len(chosen), 5)
        self.assertEqual(chosen[0], BASE + SLUGS["unknown"])  # jüngstes Datum

    def test_crawl_reads_sitemap_once_with_the_larger_xml_limit_and_only_selected_details(self):
        result = run(location="Waiblingen")
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(Fake.fetched[0], SITEMAP_URL)
        self.assertEqual(Fake.options[0], {"accept_xml": True, "max_body": MAX_SITEMAP})
        self.assertNotIn(BASE + SLUGS["hamburg"], Fake.fetched)
        self.assertEqual(len(Fake.fetched), 1 + 3)
        jobs = {job["url"]: job for job in result["jobs"]}
        self.assertEqual(set(jobs), {BASE + SLUGS["waiblingen"], BASE + SLUGS["fellbach"], BASE + SLUGS["unknown"]})
        job = jobs[BASE + SLUGS["waiblingen"]]
        self.assertEqual(job["company"], "Lidl Vertriebs-GmbH & Co. KG, Erlensee Süd")
        self.assertIn("Waiblingen", job["location"])
        self.assertIn("Anzeigen im Sitemap", result["sources"][0]["detail"])

    def test_only_the_configured_number_of_details_is_fetched(self):
        many = "".join(block(f"{BASE}verkaeufer-m-w-d-waiblingen-{760000 + n}") for n in range(70))
        sitemap = SITEMAP.replace("</urlset>", many + "</urlset>")
        with mock.patch.object(__import__("test_lidl"), "SITEMAP", sitemap):
            run(location="Waiblingen")
        self.assertEqual(len(Fake.fetched), 1 + registry()["lidl"].max_details)

    def test_registry_binding(self):
        source = registry()["lidl"]
        self.assertEqual((source.adapter, source.api, source.hosts), ("lidl_sitemap", SITEMAP_URL, ("jobs.lidl.de",)))
        row = {"key": "other", "label": "x", "hosts": ["jobs.lidl.de"], "search": "https://jobs.lidl.de/suche", "detail": "^/jobs/x$",
               "adapter": "lidl_sitemap", "api": SITEMAP_URL}
        with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([row])}):
            with self.assertRaises(ValueError):
                registry()


if __name__ == "__main__":
    unittest.main()
