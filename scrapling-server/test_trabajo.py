"""Trabajo.org (de.trabajo.org): server-rendered search reader.

Fixtures mirror the observed public result page (li.nf-job teasers with the
place in .nf-job-list-info, pagination as ?page=N) and a real detail page whose
ld+json JobPosting names the advertising employer, not Trabajo.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
from safe_http import FetchError
from sources import AGGREGATOR_SOURCES, approved_sources, registry
from trabajo_adapter import search_url, slug, trabajo

HOST = "de.trabajo.org"
BASE = f"https://{HOST}"
SEARCH = f"{BASE}/stellenangebote-verkauf/waiblingen"
ROBOTS = ("User-agent: *\nCrawl-delay: 1\nDisallow: /njob/\nDisallow: /ajax/\nDisallow: /redirect\n"
          "Disallow: /publish/\nDisallow: /account/\nAllow: /\n\nSitemap: https://sitemaps.trabajo.org/index.xml")

ADS = {
    "waiblingen": ("5506-85c1600b17172e5f5f658320295ab06c", "Verkäufer mit Stellvertretung Teilzeit",
                   "Lidl Stuttgart Nord", "Waiblingen, Baden-Württemberg, Deutschland", "71332"),
    "fellbach": ("1403-5ac7353ea1f383bb03ec9fa6701ed1ee", "Verkäufer (m/w/d)",
                 "Takko Holding", "Fellbach, Baden-Württemberg, Deutschland", "70734"),
    "hamburg": ("3289-1be9a578fc2109cfc0523270deb09c58", "Verkäufer (m/w/d)",
                "Decathlon Deutschland", "Hamburg, Hamburg, Deutschland", "20095"),
}


def ad_url(name):
    return f"{BASE}/stellenangebot-{ADS[name][0]}"


def teaser(name):
    _, title, company, place, _ = ADS[name]
    return (f'<li class="nf-job list-group-item mb-3 job-item" data-url="{ad_url(name)}" title="{title}">'
            f'<h3 class="mb-0 h2"><a href="{ad_url(name)}" title="{title}">{title}</a></h3>'
            '<div class="nf-job-list-desc mt-4"><div class="nf-job-list-info d-flex flex-wrap mb-2">'
            f'<span><i class="lnr lnr-map-marker mr-2"></i>{place}</span>'
            f'<span><i class="lnr lnr-briefcase mr-2"></i>{company}</span>'
            '<span><i class="lnr lnr-clock mr-2"></i>Vollzeit</span></div>'
            '<p class="mb-0">Du erfüllst Kundenwünsche und behältst als Verkaufstalent den Überblick.</p>'
            "</div></li>")


def results(*names, page=1, last=2):
    """A result page; the pager offers the following page like the live site."""
    nav = "".join(
        f'<li class="page-item"><a href="{SEARCH}?page={number}">{number}</a></li>'
        for number in range(1, last + 1) if number != page)
    return ("<html><body><ul class=\"list-group nf-job-list\">" + "".join(teaser(name) for name in names) + "</ul>"
            '<nav aria-label="Page navigation"><ul class="pagination">'
            f'<li class="page-item active"><a href="{SEARCH}">{page}</a></li>{nav}</ul></nav>'
            # Links that must never be followed as ads.
            f'<a href="{BASE}/redirect/5506">Bewerben</a><a href="{BASE}/stellenangebote-verkauf">Verkauf</a>'
            f'<a href="https://evil.test/stellenangebot-5506-{"a" * 32}">evil</a>'
            "</body></html>")


def posting(name, **changes):
    _, title, company, place, postal = ADS[name]
    city, region, _ = [part.strip() for part in place.split(",")]
    row = {"@context": "https://schema.org", "@type": "JobPosting", "title": title,
           "datePosted": "2026-11-20T16:13:58+01:00", "validThrough": "2099-11-27T23:59:59+01:00",
           "description": "<p>Du berätst Kunden im Verkauf und übernimmst die Stellvertretung der Filialleitung.</p>",
           "hiringOrganization": {"@type": "Organization", "name": company},
           "jobLocation": {"@type": "Place", "address": {
               "@type": "PostalAddress", "addressLocality": city, "addressRegion": region,
               "postalCode": postal, "addressCountry": "DE"}}}
    row.update(changes)
    return '<html><head><script type="application/ld+json">' + json.dumps(row) + "</script></head><body></body></html>"


NATIONWIDE = f"{BASE}/stellenangebote-verkauf"
PAGES = {
    SEARCH: results("waiblingen", "hamburg", page=1),
    f"{SEARCH}?page=2": results("fellbach", page=2),
    # Search without a place: the keyword route, one page only.
    NATIONWIDE: results("waiblingen", "hamburg", "fellbach", page=1, last=1),
}
DETAILS = {ad_url(name): posting(name) for name in ADS}


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
        if raw in PAGES:
            return raw, PAGES[raw]
        if raw in DETAILS:
            return raw, DETAILS[raw]
        raise FetchError("gone", http_status=404)


def run(q="Verkauf", location="Waiblingen", radius_km=25):
    Fake.fetched, Fake.options = [], []
    req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=["trabajo"])
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "trabajo"}):
        return crawler.crawl(req, Fake)


class TrabajoUrls(unittest.TestCase):
    def test_keyword_and_place_become_path_segments(self):
        self.assertEqual(search_url("Verkauf", "Waiblingen"), SEARCH)
        self.assertEqual(search_url("Verkäufer Teilzeit", "Schwäbisch Gmünd"),
                         f"{BASE}/stellenangebote-verkaeufer-teilzeit/schwaebisch-gmuend")

    def test_place_alone_uses_the_town_index(self):
        # The catalog has no keyword. /stellenangebote/<Ort> is the portal's own place list
        # (about 20 ads per page, 50 pages for Waiblingen), not the nationwide /stellenangebote.
        self.assertEqual(search_url("", "Waiblingen"), f"{BASE}/stellenangebote/Waiblingen")
        self.assertEqual(search_url("", "Schwäbisch Gmünd"),
                         f"{BASE}/stellenangebote/Schw%C3%A4bisch%20Gm%C3%BCnd")
        self.assertEqual(search_url("", ""), f"{BASE}/stellenangebote")
        self.assertEqual(search_url("Verkauf", ""), f"{BASE}/stellenangebote-verkauf")

    def test_query_cannot_add_a_host_query_or_path_segment(self):
        self.assertEqual(slug("../../etc/passwd?x=1&y=2"), "etc-passwd-x-1-y-2")
        for raw in ("Verkauf/../../evil", "Verkauf?page=9", "Verkauf#x", "Verkauf https://evil.test"):
            with self.subTest(raw=raw):
                url = search_url(raw, "Waiblingen")
                self.assertTrue(url.startswith(f"{BASE}/stellenangebote-"))
                self.assertEqual(url.count("/"), 4)
                self.assertNotIn("?", url)
                self.assertNotIn("#", url)
                self.assertNotIn("evil.test", url)


class TrabajoCrawl(unittest.TestCase):
    def test_catalog_reads_more_than_ten_details_and_three_pages(self):
        source = registry()["trabajo"]
        start = search_url("", "Waiblingen")
        fetched = []

        def get(url, source):
            fetched.append(url)
            if "/stellenangebot-" in url:
                return url, posting("waiblingen")
            number = int(url.split("page=")[-1]) if "page=" in url else 1
            links = "".join(f'<a href="{BASE}/stellenangebot-5506-{i:032x}">Verkauf</a>'
                            for i in range((number - 1) * 4, number * 4))
            following = (f'<nav aria-label="Page navigation"><a href="{start}?page={number + 1}">Weiter</a></nav>'
                         if number < 5 else "")
            return url, links + following

        req = SimpleNamespace(q="", location="Waiblingen", radius_km=25, max_details=100, max_pages=4)
        report = {"filtered": 0}
        jobs = list(trabajo(source, req, get, report))
        self.assertEqual(len(jobs), 16)
        self.assertEqual(len(fetched), 20)
        self.assertNotIn(start + "?page=5", fetched)
        self.assertEqual(report["urls"], 16)

    def test_live_defaults_still_limit_detail_requests_to_ten(self):
        source = registry()["trabajo"]
        fetched = []

        def get(url, source):
            fetched.append(url)
            if "/stellenangebot-" in url:
                return url, posting("waiblingen")
            return url, "".join(f'<a href="{BASE}/stellenangebot-5506-{i:032x}">Verkauf</a>'
                                for i in range(20))

        req = SimpleNamespace(q="Verkauf", location="Waiblingen", radius_km=25)
        self.assertEqual(len(list(trabajo(source, req, get, {"filtered": 0}))), 10)
        self.assertEqual(len(fetched), 11)

    def test_only_ads_in_the_radius_are_fetched_across_pages(self):
        result = run()
        self.assertEqual(result["sources"][0]["status"], "done")
        # Both result pages are read first, then only the two ads in the radius. Hamburg is never
        # requested, and neither is /redirect, the search list itself or the look-alike host.
        self.assertEqual(Fake.fetched, [SEARCH, f"{SEARCH}?page=2", ad_url("waiblingen"), ad_url("fellbach")])
        self.assertEqual([job["company"] for job in result["jobs"]], ["Lidl Stuttgart Nord", "Takko Holding"])
        self.assertEqual([job["location"] for job in result["jobs"]],
                         ["71332 Waiblingen Baden-Württemberg DE", "70734 Fellbach Baden-Württemberg DE"])

    def test_verified_location_outside_the_radius_is_dropped_after_the_detail_page(self):
        # The teaser says Waiblingen, the verified JobPosting says Hamburg: the ad must not count.
        with mock.patch.dict(DETAILS, {ad_url("waiblingen"): posting("waiblingen", jobLocation={
                "@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Hamburg",
                                              "postalCode": "20095", "addressCountry": "DE"}})}):
            result = run()
        self.assertEqual([job["company"] for job in result["jobs"]], ["Takko Holding"])
        self.assertEqual(result["sources"][0]["filtered"], 1)

    def test_without_a_place_every_listed_ad_counts(self):
        result = run(location="")
        self.assertEqual({job["company"] for job in result["jobs"]},
                         {"Lidl Stuttgart Nord", "Takko Holding", "Decathlon Deutschland"})

    def test_expired_ad_is_not_kept(self):
        with mock.patch.dict(DETAILS, {ad_url("waiblingen"): posting("waiblingen", validThrough="2020-01-01")}):
            result = run()
        self.assertEqual([job["company"] for job in result["jobs"]], ["Takko Holding"])

    def test_report_counts_listed_and_nearby_ads(self):
        report = run()["sources"][0]
        self.assertEqual((report["urls"], report["matched"], report["kept"]), (3, 2, 2))
        self.assertIn("im Umkreis", report["detail"])


class TrabajoRegistry(unittest.TestCase):
    def test_binding_and_limits(self):
        source = registry()["trabajo"]
        self.assertEqual((source.adapter, source.hosts, source.api), ("trabajo_search", (HOST,), ""))
        self.assertEqual((source.max_pages, source.max_details), (3, 10))
        self.assertIn("Waiblingen", source.catalog_locations)
        self.assertLessEqual(len(source.catalog_locations), 8)
        self.assertTrue(source.teaser and source.teaser_location)

    def test_reader_is_bound_to_the_public_german_search(self):
        for change in ({"search": f"https://{HOST}/stellenangebote-verkauf"}, {"key": "other"},
                       {"api": f"https://{HOST}/sitemap.xml"}):
            row = {"key": "trabajo", "label": "Trabajo.org", "hosts": [HOST], "adapter": "trabajo_search",
                   "search": f"https://{HOST}/stellenangebote", "detail": r"^/stellenangebot-\d+-[a-f0-9]{32}/?$",
                   **change}
            with self.subTest(change=change):
                with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([row])}):
                    with self.assertRaises(ValueError):
                        registry()

    def test_nationwide_board_is_never_approved_through_the_employer_group(self):
        self.assertIn("trabajo", AGGREGATOR_SOURCES)
        with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            self.assertNotIn("trabajo", approved_sources())
        with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "trabajo"}):
            self.assertIn("trabajo", approved_sources())


if __name__ == "__main__":
    unittest.main()
