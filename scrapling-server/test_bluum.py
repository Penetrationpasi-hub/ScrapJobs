"""Offline checks for bluum BW (Jobiqo). Fixture mirrors the observed public detail page."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from extraction import discovery, extract
from sources import registry, approved_sources
from crawler import crawl

URL = "https://bw.bluum.de/job/kundendienstmonteur-heizung-sanitaer-mwd-252503"
ESCAPED = ("&lt;p&gt;&lt;strong&gt;Service | Wartung | Reparatur – Greiner Energie- und Versorgungstechnik in Geislingen&lt;/strong&gt;&lt;/p&gt;"
           "&lt;p&gt;Du kennst dich mit Heizungs- und Sanitärtechnik aus.&amp;nbsp;&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Wartung und Instandhaltung "
           "von Heizungs- und Sanitäranlagen&lt;/li&gt;&lt;li&gt;Fehlersuche und Störungsbeseitigung&lt;/li&gt;&lt;/ul&gt;&lt;p&gt;"
           "&lt;a href=&quot;mailto:info@greiner-energietechnik.de&quot;&gt;info@greiner-energietechnik.de&lt;/a&gt;&lt;/p&gt;")


def page(**changes):
    posting = {"@context": "https://schema.org", "@type": "JobPosting",
               "title": "Kundendienstmonteur Heizung &amp; Sanitär (m/w/d)", "description": ESCAPED,
               "datePosted": "2026-08-28T14:54:09+02:00", "validThrough": "2099-11-11T23:54:09+01:00",
               "employmentType": "FULL_TIME", "directApply": "True",
               "hiringOrganization": {"@type": "Organization", "name": "Greiner Energie- und Versorgungstechnik",
                                      "sameAs": "https://bw.bluum.de/organization/greiner-energie-und-versorgungstechnik"},
               "jobLocation": {"@type": "Place", "address": {
                   "@type": "PostalAddress", "addressLocality": "Geislingen an der Steige",
                   "addressRegion": "Baden-Württemberg", "addressCountry": "DE", "postalCode": "73312"}}}
    posting.update(changes)
    org = {"@context": "https://schema.org", "@type": "Organization", "name": "Bluum Baden-Württemberg"}
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": []}
    return "".join('<script type="application/ld+json">' + json.dumps(x) + "</script>" for x in (org, crumbs, posting))


def teaser(number, place):
    location = f'<div data-testid="jcl-job-teaser-location"><span>{place}</span></div>' if place else ""
    return (f'<div data-test-id="job-teaser-{number} "><div><a data-avoid-redirect="true" href="/job/elektroniker-mwd-{number}">Elektroniker</a>'
            f'<a id="job-teaser-company-link" href="/organization/firma-{number}">Firma</a>{location}</div></div>')


class Bluum(unittest.TestCase):
    def setUp(self):
        self.source = registry()["bluum_bw"]

    def test_catalog_entry_and_search_template(self):
        self.assertTrue(self.source.available)
        self.assertEqual(self.source.hosts, ("bw.bluum.de",))
        self.assertEqual(self.source.start("Elektriker & Monteur", "Waiblingen"),
                         "https://bw.bluum.de/jobs?search=Elektriker%20%26%20Monteur")

    def test_discovery_keeps_only_job_detail_links_on_the_exact_host(self):
        html = ('<a href="/job/kundendienstmonteur-heizung-sanitaer-mwd-252503">Monteur</a>'
                '<a href="/organization/greiner-energie-und-versorgungstechnik">Firma</a>'
                '<a href="/jobs/stuttgart-0">Stuttgart (389)</a><a href="/jobs/handwerk">Handwerk</a>'
                '<a href="https://evil.test/job/monteur-mwd-1">x</a><a href="/job/wizard">Job einstellen</a>')
        links, _ = discovery(html, self.source.search, self.source, "Monteur")
        self.assertEqual(links, [URL])


    def test_search_page_links_and_pager_of_the_observed_format(self):
        html = ('<div title="x"><a data-avoid-redirect="true" href="/job/servicetechniker-elektroniker-mechatroniker-mwd-262083">Servicetechniker</a>'
                '<a id="job-teaser-company-link" href="/organization/lhyfe-gmbh">Lhyfe GmbH</a></div>'
                '<a data-avoid-redirect="true" href="/job/bilanzbuchhalter-mwd-263511">Bilanz</a>'
                '<nav role="navigation"><ul><li>1 / 9</li><li><a data-testid="pager_next" href="/jobs?search=elektro&amp;page=2">Nächste</a></li></ul></nav>')
        links, following = discovery(html, "https://bw.bluum.de/jobs?search=elektro", self.source, "elektro")
        self.assertEqual(links, ["https://bw.bluum.de/job/servicetechniker-elektroniker-mechatroniker-mwd-262083",
                                 "https://bw.bluum.de/job/bilanzbuchhalter-mwd-263511"])
        self.assertEqual(following, "https://bw.bluum.de/jobs?search=elektro&page=2")

    def test_real_employer_not_the_portal_and_clean_description(self):
        job = extract(page(), URL, self.source, "Kundendienst")
        self.assertEqual(job["company"], "Greiner Energie- und Versorgungstechnik")
        self.assertEqual(job["title"], "Kundendienstmonteur Heizung & Sanitär (m/w/d)")
        self.assertIn("73312 Geislingen an der Steige", job["location"])
        self.assertEqual(job["posted"], "2026-08-28")
        self.assertNotIn("<", job["description"])
        self.assertNotIn("&lt;", job["description"])
        self.assertIn("Wartung und Instandhaltung", job["description"])

    def test_portal_listing_other_host_expired_and_initiative_are_dropped(self):
        self.assertIsNone(extract(page(), "https://bw.bluum.de/jobs/handwerk", self.source, "Kundendienst"))
        self.assertIsNone(extract(page(), URL.replace("bw.bluum.de", "evil.test"), self.source, "Kundendienst"))
        self.assertIsNone(extract(page(validThrough="2020-01-01T00:00:00+01:00"), URL, self.source, "Kundendienst"))
        self.assertIsNone(extract(page(title="Initiativbewerbung"), URL, self.source, "Initiativ"))
        self.assertIsNone(extract(page(hiringOrganization={"@type": "Organization", "name": ""}), URL, self.source, "Kundendienst"))
        self.assertIsNone(extract(page(), URL, self.source, "Buchhalter"))

    def test_ten_second_crawl_delay_fits_the_run_budget(self):
        slugs = [f"elektroniker-mwd-{n}" for n in range(263001, 263011)]
        search = "".join(f'<a href="/job/{slug}">Elektroniker</a>' for slug in slugs)
        clock, pauses, fetched = [100.0], [], []
        robots = "Sitemap: https://bw.bluum.de/sitemap.xml\nUser-agent: *\nCrawl-delay: 10\nAllow: /\nDisallow: /api/gmapi"

        def sleep(seconds):
            pauses.append(seconds)
            clock[0] += seconds

        def factory(budget):
            class Fixture:
                def __init__(self):
                    self.last = {}

                def get(self, raw, hosts, authorize=None, **options):
                    if authorize:
                        authorize(raw)
                    budget.claim()
                    self.last[urlsplit(raw).hostname] = clock[0]
                    if raw.endswith("/robots.txt"):
                        return raw, robots
                    fetched.append(raw)
                    if raw.startswith("https://bw.bluum.de/jobs"):
                        return raw, search
                    return raw, page(title="Elektroniker (m/w/d)")
            return Fixture()

        start = clock[0]
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "bluum_bw"}), \
                patch("crawler.time.monotonic", side_effect=lambda: clock[0]), \
                patch("crawler.time.sleep", side_effect=sleep):
            result = crawl(SimpleNamespace(q="Elektroniker", location="", sources=["bluum_bw"]), factory)
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(len(fetched), 1 + 10)  # one search page (no pager link), at most ten details
        self.assertNotIn("page=2", " ".join(fetched))
        self.assertEqual(len(result["jobs"]), 10)
        self.assertLess(clock[0] - start, 140)
        self.assertEqual(set(pauses), {10})

    def test_teaser_places_skip_ads_outside_the_radius_before_any_detail_request(self):
        import geo
        origin = geo.center("Waiblingen")
        html = (teaser(263531, "74564 Crailsheim, Deutschland") + teaser(262083, "Schwäbisch Gmünd, Deutschland")
                + teaser(263536, "04103 Leipzig, Deutschland+") + teaser(263600, "")
                + teaser(263601, "Stuttgart, Deutschland") + teaser(263602, "Xyzdorf, Deutschland"))
        near = lambda place: geo.in_range(origin, place, 50)
        links, _ = discovery(html, "https://bw.bluum.de/jobs?search=elektro", self.source, "elektro", near)
        # Crailsheim is 60+ km away and dropped; Gmünd/Stuttgart are in range; "+" (multi-site), no place and unknown place stay.
        self.assertEqual(sorted(link.rsplit("-", 1)[1] for link in links), ["262083", "263536", "263600", "263601", "263602"])
        everything, _ = discovery(html, "https://bw.bluum.de/jobs?search=elektro", self.source, "elektro")
        self.assertEqual(len(everything), 6)

    def test_crawl_reads_a_second_list_page_to_fill_detail_slots_with_nearby_ads_only(self):
        page1 = "".join(teaser(n, place) for n, place in [
            (1001, "Stuttgart, Deutschland"), (1002, "74564 Crailsheim, Deutschland"), (1003, "Göppingen, Deutschland"),
            (1004, "Villingen-Schwenningen, Deutschland"), (1005, "04103 Leipzig, Deutschland"), (1006, "73525 Schwäbisch Gmünd, Deutschland")]
        ) + '<a data-testid="pager_next" href="/jobs?search=Elektroniker&amp;page=2">Nächste</a>'
        page2 = "".join(teaser(n, place) for n, place in [
            (2001, "71332 Waiblingen, Deutschland"), (2002, "Hamburg, Deutschland"), (2003, "71522 Backnang, Deutschland"),
            (2004, "73728 Esslingen am Neckar, Deutschland"), (2005, "Waiblingen, Deutschland")])
        fetched = []
        robots = "User-agent: *\nCrawl-delay: 10\nAllow: /"

        def factory(budget):
            class Fixture:
                def __init__(self):
                    self.last = {}

                def get(self, raw, hosts, authorize=None, **options):
                    if authorize:
                        authorize(raw)
                    budget.claim()
                    if raw.endswith("/robots.txt"):
                        return raw, robots
                    fetched.append(raw)
                    if raw.startswith("https://bw.bluum.de/jobs"):
                        return raw, page2 if "page=2" in raw else page1
                    return raw, page(title="Elektroniker (m/w/d)")
            return Fixture()

        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "bluum_bw"}), \
                patch("crawler.time.sleep", side_effect=lambda seconds: None):
            result = crawl(SimpleNamespace(q="Elektroniker", location="Waiblingen", radius_km=50, sources=["bluum_bw"]), factory)
        details = [url.rsplit("-", 1)[1] for url in fetched if "/job/" in url]
        self.assertEqual(sum("/jobs?" in url for url in fetched), 2)
        self.assertEqual(len(details), 7)
        self.assertTrue({"1002", "1004", "1005", "2002"}.isdisjoint(details), details)
        self.assertEqual(len(result["jobs"]), 7)

    def test_isolated_boards_must_run_alone_in_the_worker(self):
        from main import Search
        self.assertEqual(Search.validate_sources(["bluum_bw"]), ["bluum_bw"])
        with self.assertRaises(ValueError):
            Search.validate_sources(["bluum_bw", "festo"])
        with self.assertRaises(ValueError):
            Search.validate_sources(["bluum_bw", "rems_murr_jobs"])

    def test_aggregator_needs_explicit_approval_and_is_not_in_employers_group(self):
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            self.assertNotIn("bluum_bw", approved_sources())
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers,bluum_bw"}):
            self.assertIn("bluum_bw", approved_sources())


if __name__ == "__main__":
    unittest.main()
