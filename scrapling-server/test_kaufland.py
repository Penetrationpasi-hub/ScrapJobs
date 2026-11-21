"""Kaufland (jobs.kaufland.de): gleiche Plattform wie Lidl, Leser aus lidl_adapter. Fixtures nach der beobachteten sitemap-jobs.xml."""
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

HOST = "jobs.kaufland.de"
SITEMAP_URL = f"https://{HOST}/sitemap-jobs.xml"
BASE = f"https://{HOST}/jobs/"
SLUGS = {
    "praktikum": "schuelerpraktikum-im-verkauf-waiblingen-409355",
    "ausbildung": "ausbildung-zum-kaufmann-im-einzelhandel-m-w-d-2027-waiblingen-411737",
    "studium": "duales-studium-bwl-handel-filiale-b.a.-2027-waiblingen-407181",
    "karlsruhe": "schuelerpraktikum-im-verkauf-karlsruhe-409309",
    "mahlow": "ausbildung-zum-verkaeufer-frische-m-w-d-2027-blankenfelde-mahlow-408170",
}
ROBOTS = "User-agent: *\nDisallow: /cps/\n\nSitemap: https://jobs.kaufland.de/sitemap.xml"


def block(loc, stamp="2026-10-09T07:14:06+00:00"):
    return f"<url><loc>{loc}</loc><lastmod>{stamp}</lastmod></url>"


SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + "".join(block(BASE + slug) for slug in SLUGS.values())
           + block(f"https://{HOST}/kaufland-als-arbeitgeber/vorteile") + block("https://jobs.lidl.de/jobs/fremd-m-w-d-berlin-761201")
           + "</urlset>")


def posting():
    row = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Schülerpraktikum im Verkauf",
           "datePosted": "2026-08-31T00:00:00+00:00", "validThrough": "2027-07-31T00:00:00+00:00",
           "description": "<div><p>Du lernst den Verkauf in unserer Filiale kennen und unterstützt das Team bei allen Aufgaben.</p></div>",
           "hiringOrganization": {"@type": "Organization", "name": "Kaufland Vertrieb 244 GmbH & Co. KG"},
           "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "streetAddress": "Ruhrstraße 5",
                                                         "postalCode": "71332", "addressLocality": "Waiblingen", "addressCountry": "DE"},
                           "geo": {"@type": "GeoCoordinates", "latitude": 48.8172303, "longitude": 9.3007688}}}
    return '<html><head><script type="application/ld+json">' + json.dumps(row) + "</script></head><body></body></html>"


DETAILS = {BASE + SLUGS["praktikum"]: posting()}


class Fake:
    fetched, options = [], []

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


def run(q="Verkauf", location="Waiblingen", radius_km=25):
    Fake.fetched, Fake.options = [], []
    req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=["kaufland"])
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "kaufland"}):
        return crawler.crawl(req, Fake)


class KauflandTest(unittest.TestCase):
    def test_entries_only_for_the_kaufland_host(self):
        rows = {row[2]: row for row in entries(SITEMAP, HOST)}
        self.assertEqual(set(rows), {BASE + slug for slug in SLUGS.values()})  # weder Inhaltsseite noch Lidl-URL
        self.assertEqual(rows[BASE + SLUGS["praktikum"]][1], "")  # kein Geschlechtsmarker
        self.assertEqual(rows[BASE + SLUGS["ausbildung"]][:2], ("ausbildung-zum-kaufmann-im-einzelhandel", "2027-waiblingen"))

    def test_place_from_the_title_tail_or_after_the_year(self):
        origin = geo.center("Waiblingen")
        rows = entries(SITEMAP, HOST)
        self.assertEqual(select(rows, "Praktikum", origin, 25), [BASE + SLUGS["praktikum"]])  # Karlsruhe zu weit
        self.assertIn(BASE + SLUGS["ausbildung"], select(rows, "Ausbildung", origin, 25))  # Ort hinter der Jahreszahl
        self.assertNotIn(BASE + SLUGS["mahlow"], select(rows, "Ausbildung", origin, 25))  # Blankenfelde-Mahlow bei Berlin

    def test_crawl_reads_the_sitemap_once_and_only_selected_details(self):
        result = run()
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(Fake.fetched[0], SITEMAP_URL)
        self.assertEqual(Fake.options[0], {"accept_xml": True, "max_body": MAX_SITEMAP})
        self.assertEqual(Fake.fetched, [SITEMAP_URL, BASE + SLUGS["praktikum"]])
        self.assertEqual(result["jobs"][0]["company"], "Kaufland Vertrieb 244 GmbH & Co. KG")

    def test_registry_binding(self):
        source = registry()["kaufland"]
        self.assertEqual((source.adapter, source.api, source.hosts, source.max_details),
                         ("kaufland_sitemap", SITEMAP_URL, (HOST,), 50))
        row = {"key": "other", "label": "x", "hosts": [HOST], "search": f"https://{HOST}/jobsuche", "detail": "^/jobs/x$",
               "adapter": "kaufland_sitemap", "api": SITEMAP_URL}
        with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([row])}):
            with self.assertRaises(ValueError):
                registry()
