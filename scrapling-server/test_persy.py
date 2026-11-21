"""GPM Personalservice and Liebert via the public Persy job exchange. Fixtures mirror the observed API answer."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
from persy_adapter import BASE, PAGE, missing_robots_scope, page_url, record
from safe_http import FetchError
from sources import registry

ORG = "GPM - Gesellschaft für Personalmanagement mbH"


def row(title, city, zipcode, code, date="2026-11-07 07:24:44", org=ORG, url=None, country="Deutschland"):
    slug = f"{title.replace(' ', '-').replace('/', '-').replace('(', '').replace(')', '')}-job-in-{city.replace(' ', '-')}-{zipcode}-Baden-Wuerttemberg"
    return {"PublishingDate": date, "isRedirect": False,
            "DetailsURL": url or f"https://www.persy.jobs/persy/l/job-{code}-a-stellenangebote-{slug}",
            "Posting": {"Title": title, "OrganisationUnit": {"Name": org},
                        "Locations": [{"CityName": city, "ZipCode": zipcode, "AddressLine": None,
                                       "Region": {"RegionName": "Baden-Württemberg"},
                                       "Country": {"CountryName": country, "ISOCode": None}}]}}


ROWS = [
    row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", "jsjcn"),
    row("Aluschweißer (m/w/d)", "Ebersbach an der Fils", "73061", "judvr"),
    row("Elektriker/Elektroniker (m/w/d)", "Renningen", "71272", "judvo"),
    row("Lagerist (m/w/d)", "Waiblingen", "71332", "judvx"),
    row("Lagerist (m/w/d)", "Hamburg", "20095", "judvy"),
    row("Staplerfahrer (m/w/d)", "Winnenden, Württemberg", "71364", "judvz"),
]
ROBOTS_404 = object()


class Fake:
    fetched = []
    options = []
    pages = {}
    robots = ROBOTS_404

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            if Fake.robots is ROBOTS_404:
                raise FetchError("gone", http_status=404)
            if isinstance(Fake.robots, FetchError):
                raise Fake.robots
            return raw, Fake.robots
        if authorize:
            authorize(raw)
        Fake.fetched.append(raw)
        Fake.options.append(kw)
        return raw, json.dumps(Fake.pages.get(raw, []))


def run(q="Lager", location="", radius_km=25, rows=None, pages=None, robots=ROBOTS_404, key="gpm"):
    Fake.fetched, Fake.options, Fake.robots = [], [], robots
    Fake.pages = pages if pages is not None else {page_url(0, key): ROWS if rows is None else rows}
    req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=[key])
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": key}):
        return crawler.crawl(req, Fake)


class PersyTest(unittest.TestCase):
    def test_list_page_url_is_the_widgets_own_query_with_a_small_field_list(self):
        url = page_url(100)
        self.assertTrue(url.startswith(BASE + "?options="))
        self.assertIn("%22offset%22%3A%5B%7B%22eq%22%3A100%7D%5D", url)
        self.assertIn("filters={}", url)
        self.assertIn("Posting.Title", url)
        self.assertEqual(PAGE, 100)  # the API rejects larger limits

    def test_reads_jobs_with_employer_place_date_and_public_link_without_fetching_details(self):
        result = run(q="Lager")
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(Fake.fetched, [page_url(0)])
        self.assertEqual(Fake.options, [{"accept_json": True}])
        jobs = {job["title"]: job for job in result["jobs"]}
        self.assertEqual(set(jobs), {"Lagerhelfer (m/w/d)", "Lagerist (m/w/d)"})
        first = result["jobs"][0]
        self.assertEqual(first["company"], ORG)
        self.assertIn("71384 Weinstadt", first["location"])
        self.assertEqual(first["posted"], "2026-11-07")
        self.assertTrue(first["url"].startswith("https://www.persy.jobs/persy/l/job-jsjcn-a-stellenangebote-Lagerhelfer"))
        self.assertEqual(len(result["jobs"]), 3)  # Lagerhelfer + Lagerist Waiblingen + Lagerist Hamburg (no place set)

    def test_a_search_place_drops_far_ads_and_lists_the_nearest_first(self):
        result = run(q="Lager", location="Waiblingen", radius_km=25)
        self.assertEqual([job["title"] + job["location"][:6] for job in result["jobs"]],
                         ["Lagerist (m/w/d)71332 ", "Lagerhelfer (m/w/d)71384 "])
        self.assertNotIn("Hamburg", json.dumps(result["jobs"]))

    def test_unknown_place_is_kept_after_the_known_ones(self):
        odd = row("Lagerist (m/w/d)", "Xyzdorf", "", "judwa")
        result = run(q="Lager", location="Waiblingen", rows=[odd, ROWS[0]])
        self.assertEqual([job["location"][:6] for job in result["jobs"]], ["71384 ", "Xyzdor"])

    def test_title_must_match_the_query_at_a_word_start(self):
        self.assertEqual(run(q="Elektro")["jobs"][0]["title"], "Elektriker/Elektroniker (m/w/d)")
        self.assertEqual(run(q="Buchhalter")["jobs"], [])

    def test_wrong_employer_or_foreign_link_is_dropped(self):
        rows = [row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", "aaaaa", org=""),
                row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", "bbbbb", url="https://evil.test/persy/l/job-bbbbb-a-stellenangebote-Lager"),
                row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", "ccccc", url="https://www.persy.jobs/persy/l/job-ccccc-a-stellenangebote-Lager?x=1"),
                row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", "ddddd", url="https://www.persy.jobs/other/job-ddddd")]
        result = run(rows=rows)
        self.assertEqual(result["jobs"], [])
        self.assertGreaterEqual(result["sources"][0]["filtered"], 4)
        self.assertIsNone(record({"DetailsURL": 5}))

    def test_a_full_page_requests_the_next_offset_and_a_short_page_ends_the_list(self):
        full = [row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", f"p{i:04d}") for i in range(100)]
        result = run(pages={page_url(0): full, page_url(100): ROWS[:1] + [row("Lagerist (m/w/d)", "Waiblingen", "71332", "judvx")]})
        self.assertEqual(Fake.fetched, [page_url(0), page_url(100)])
        self.assertEqual(len(result["jobs"]), 30)  # worker result cap, nearest first

    def test_at_most_five_pages_and_the_cut_off_is_reported(self):
        full = [row("Lagerhelfer (m/w/d)", "Weinstadt", "71384", f"q{i:04d}") for i in range(100)]
        result = run(pages={page_url(offset): full for offset in range(0, 600, 100)})
        self.assertEqual(len(Fake.fetched), 5)
        self.assertIn("mehr als 500", result["sources"][0]["detail"])

    def test_a_non_list_answer_is_reported(self):
        result = run(pages={page_url(0): {"error": "x"}})
        self.assertEqual(result["sources"][0]["status"], "unsupported")

    def test_missing_robots_404_counts_as_no_rules_for_these_list_pages_only(self):
        self.assertEqual(run()["sources"][0]["status"], "done")
        source = registry()["gpm"]
        options = {"accept_json": True}
        self.assertTrue(missing_robots_scope(page_url(0), source, options))
        self.assertTrue(missing_robots_scope(page_url(400), source, options))
        for raw, opts in ((page_url(500), options), (page_url(0).replace("dG9juJve", "other"), options),
                          (page_url(0) + "&x=1", options), (BASE, options), ("https://www.persy.jobs/persy/l/job-x-a-stellenangebote-y", options),
                          (page_url(0), {"accept_json": True, "json_body": {}}), (page_url(0), {})):
            self.assertFalse(missing_robots_scope(raw, source, opts), (raw, opts))
        from dataclasses import replace
        self.assertFalse(missing_robots_scope(page_url(0), replace(source, key="other"), options))

    def test_a_blocked_robots_answer_still_stops_the_reader(self):
        result = run(robots=FetchError("blocked", http_status=403))
        self.assertEqual(result["sources"][0]["status"], "robots_unavailable")
        self.assertEqual(Fake.fetched, [])

    def test_a_published_robots_file_is_honoured(self):
        result = run(robots="User-agent: *\nDisallow: /persy/\n")
        self.assertEqual(result["sources"][0]["status"], "robots_denied")
        self.assertEqual(Fake.fetched, [])

    def test_liebert_reads_its_own_exchange_token(self):
        liebert = [
            row("Montierer (m/w/d)", "Waiblingen", "71332", "jsafi", org="Liebert GmbH Personaldienstleistungen"),
            row("Gabelstaplerfahrer (m/w/d)", "Dornstadt", "89160", "js2b6", org="Liebert GmbH - Göppingen"),
            row("Schlosser (m/w/d) (copy)", "Zell unter Aichelberg", "73119", "juz2w", org="Liebert GmbH - Göppingen"),
        ]
        result = run(q="Schlosser", rows=liebert, key="liebert")
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(Fake.fetched, [page_url(0, "liebert")])
        self.assertIn("/jobexchange/eusdDOss/", Fake.fetched[0])
        self.assertEqual([j["title"] for j in result["jobs"]], ["Schlosser (m/w/d) (copy)"])
        self.assertEqual(result["jobs"][0]["company"], "Liebert GmbH - Göppingen")
        near = run(q="Montierer", location="Waiblingen", radius_km=10, rows=liebert, key="liebert")
        self.assertEqual([j["title"] for j in near["jobs"]], ["Montierer (m/w/d)"])

    def test_robots_exception_is_scoped_per_source_and_token(self):
        registry_ = registry()
        options = {"accept_json": True}
        self.assertTrue(missing_robots_scope(page_url(0, "liebert"), registry_["liebert"], options))
        self.assertFalse(missing_robots_scope(page_url(0, "gpm"), registry_["liebert"], options))
        self.assertFalse(missing_robots_scope(page_url(0, "liebert"), registry_["gpm"], options))

    def test_registry_binding(self):
        self.assertEqual(registry()["liebert"].api, page_url(0, "liebert").split("?")[0])
        source = registry()["gpm"]
        self.assertEqual((source.adapter, source.api, source.hosts),
                         ("persy_exchange", BASE, ("www.germanpersonnel.de", "www.persy.jobs")))
        with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([{
                "key": "gpm2", "label": "x", "hosts": ["www.germanpersonnel.de", "www.persy.jobs"], "search": BASE,
                "detail": "^/persy/l/job-.+$", "adapter": "persy_exchange",
                "api": BASE.replace("dG9juJve", "other")}])}):
            with self.assertRaises(ValueError):
                registry()
        with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([{
                "key": "liebert2", "label": "x", "hosts": ["www.germanpersonnel.de", "www.persy.jobs"], "search": BASE,
                "detail": "^/persy/l/job-.+$", "adapter": "persy_exchange", "api": BASE}])}):
            with self.assertRaises(ValueError):
                registry()


if __name__ == "__main__":
    unittest.main()
