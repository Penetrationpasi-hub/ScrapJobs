"""Deutsche Post / DHL via the Phenom search widget (POST /widgets with session cookie and CSRF token)."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
import batch
from phenom_adapter import PAGE, record, slug
from safe_http import Budget, FetchError, Transport, store_cookies
from sources import PHENOM_TENANTS, registry

TENANT = PHENOM_TENANTS["deutsche_post"]
SEARCH = ('<html><script>phApp.pageId = "page12-ds"; phApp.sessionParams = {"referer":"x","csrfToken":"31f0d48553b3498b83d06f86d83074f3"};'
          'phApp.siteConfig = {"locale":"de_eu"};</script></html>')


def hit(ident, title, city, lat, lon, country="Germany", posted="2026-11-17T00:00:00.000+0000", teaser="Du bist gern unterwegs."):
    return {"jobSeqNo": ident, "jobId": "AV-1", "title": title, "city": city, "state": "Baden-Württemberg", "country": country,
            "latitude": str(lat), "longitude": str(lon), "postedDate": posted, "descriptionTeaser": teaser, "applyUrl": "x"}


JOBS = [
    hit("DPDHGLOBALAV137053DEEUEXTERNAL", "Postbote für Pakete und Briefe (m/w/d) in Waiblingen", "Waiblingen", 48.83, 9.32),
    hit("DPDHGLOBALAV137054DEEUEXTERNAL", "Postbote für Pakete und Briefe (m/w/d) in Hamburg", "Hamburg", 53.55, 10.0),
    hit("DPDHGLOBALAV137055DEEUEXTERNAL", "Postbote (m/w/d) in Krakau", "Krakau", 50.06, 19.94, country="Poland"),
    hit("DPDHGLOBALAV137056DEEUEXTERNAL", "Postbote (m/w/d) in Stuttgart", "Stuttgart", 48.78, 9.18),
]


class Fake:
    calls = []
    jar = {}
    responses = {}

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            return raw, "User-agent: *\nDisallow: */apply\n"
        if authorize:
            authorize(raw)
        Fake.calls.append((raw, kw))
        if "json_body" not in kw:
            kw["cookies"]["PLAY_SESSION"] = "abc"
            return raw, Fake.responses.get("page", SEARCH)
        body = kw["json_body"]
        return raw, json.dumps(Fake.responses["widgets"](body))


def reply(jobs, total=None, facets=True):
    def build(body):
        out = {"refineSearch": {"status": 200, "hits": len(jobs), "totalHits": len(jobs) if total is None else total,
                                "data": {"jobs": jobs}}}
        if facets:
            out["aggregations"] = [{"field": "country", "value": {"Poland": 3, "Germany": 90}}]
        return out
    return build


def run(q="Postbote", location="", radius_km=25, widgets=None, page=None):
    Fake.calls, Fake.responses = [], {"widgets": widgets or reply(JOBS)}
    if page is not None:
        Fake.responses["page"] = page
    req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=["deutsche_post"])
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "deutsche_post"}):
        return crawler.crawl(req, Fake)


class PhenomTest(unittest.TestCase):
    def test_session_page_then_widget_search_with_token_cookie_and_referer(self):
        result = run()
        self.assertEqual(result["sources"][0]["status"], "done")
        page, search = Fake.calls[0], Fake.calls[1]
        self.assertEqual(page[0], "https://careers.dhl.com/eu/de/search-results?keywords=Postbote")
        self.assertEqual(search[0], "https://careers.dhl.com/widgets")
        self.assertEqual(search[1]["extra_headers"]["X-CSRF-Token"], "31f0d48553b3498b83d06f86d83074f3")
        self.assertEqual(search[1]["extra_headers"]["Referer"], page[0])
        self.assertEqual(search[1]["cookies"], {"PLAY_SESSION": "abc"})
        body = search[1]["json_body"]
        self.assertEqual((body["ddoKey"], body["keywords"], body["pageId"], body["from"], body["size"]),
                         ("refineSearch", "Postbote", "page12-ds", 0, PAGE))
        self.assertEqual((body["lang"], body["country"]), ("de_eu", "eu"))  # aus "locale" der Seite

    def test_german_ads_only_and_job_urls_from_the_ad_identifier(self):
        jobs = {j["title"]: j for j in run()["jobs"]}
        self.assertNotIn("Postbote (m/w/d) in Krakau", jobs)  # Polen
        first = jobs["Postbote für Pakete und Briefe (m/w/d) in Waiblingen"]
        self.assertEqual(first["url"], "https://careers.dhl.com/eu/de/job/DPDHGLOBALAV137053DEEUEXTERNAL/Postbote-f%C3%BCr-Pakete-und-Briefe-m-w-d-in-Waiblingen")
        self.assertEqual((first["company"], first["posted"]), ("Deutsche Post DHL Group", "2026-11-17"))
        self.assertIn("Waiblingen", first["location"])

    def test_location_is_sent_as_coordinates_and_radius(self):
        bodies = []

        def widgets(body):
            bodies.append(body)
            return reply(JOBS)(body)
        result = run(location="Waiblingen", radius_km=30, widgets=widgets)
        place = bodies[0]["locationData"]
        self.assertEqual((place["placeVal"], place["sliderRadius"], place["LocationUnit"], place["aboveMaxRadius"]),
                         ("Waiblingen", 30, "kilometers", False))
        self.assertAlmostEqual(float(place["latitude"]), 48.84, delta=0.1)
        self.assertTrue(bodies[0]["isSliderEnable"])
        self.assertEqual([j["title"] for j in result["jobs"]],
                         ["Postbote für Pakete und Briefe (m/w/d) in Waiblingen", "Postbote (m/w/d) in Stuttgart"])
        run(widgets=widgets)
        self.assertEqual(bodies[-1]["locationData"], {})

    def test_more_pages_are_read_up_to_the_limit_and_reported(self):
        full = [hit(f"DPDHGLOBALAV{n:06d}DEEUEXTERNAL", f"Postbote {n}", "Stuttgart", 48.78, 9.18) for n in range(PAGE)]
        offsets = []

        def widgets(body):
            offsets.append(body["from"])
            page = [{**row, "jobSeqNo": f"DPDHGLOBALAV{body['from'] + n:06d}DEEUEXTERNAL"}
                    for n, row in enumerate(full)]
            return reply(page, total=900)(body)
        result = run(widgets=widgets)
        self.assertEqual(offsets, list(range(0, PAGE * 8, PAGE)))
        self.assertIn("900 Treffer (Suche, de_eu, Ort nein), 80 gelesen", result["sources"][0]["detail"])
        self.assertEqual(result["sources"][0]["status"], "result_limit")

    def test_zero_kept_jobs_say_why_in_the_status_line(self):
        abroad = [hit(f"DPDHGLOBALAV{n:06d}DEEUEXTERNAL", f"Postbote {n}", "Krakau", 50.06, 19.94, country="Polen") for n in range(5)]
        result = run(widgets=reply(abroad, total=5, facets=False))
        detail = result["sources"][0]["detail"]
        self.assertIn("5 Treffer (Suche, de_eu, Ort nein), 5 gelesen (Seiten [5])", detail)
        self.assertIn("anderes Land: Polen×5", detail)
        self.assertEqual(result["jobs"], [])

    def test_page_without_token_is_reported(self):
        result = run(page="<html>Cookie-Banner</html>")
        self.assertEqual(result["sources"][0]["status"], "unsupported")
        self.assertIn("kein csrfToken/pageId", result["sources"][0]["detail"])

    def test_rejected_widget_answer_without_embedded_hits_is_reported(self):
        result = run(widgets=lambda body: {"refineSearch": {"status": 403, "data": None}})
        self.assertEqual(result["sources"][0]["status"], "unsupported")
        self.assertIn("Widget-Antwort", result["sources"][0]["detail"])

    def test_record_needs_identifier_title_and_germany(self):
        self.assertIsNone(record(TENANT, {"title": "x", "country": "Germany"}))
        self.assertIsNone(record(TENANT, {"jobSeqNo": "../x", "title": "x", "country": "Germany"}))
        self.assertIsNotNone(record(TENANT, {"jobSeqNo": "ABC123", "title": "x", "country": "Deutschland"}))
        self.assertEqual(slug("Ausbildung zum Industriekaufmann/-frau (m/w/d)"), "Ausbildung-zum-Industriekaufmann-frau-m-w-d")

    def test_registry_binding(self):
        source = registry()["deutsche_post"]
        self.assertEqual((source.adapter, source.api), ("phenom_widgets", "https://careers.dhl.com/widgets"))
        row = {"key": "other", "label": "x", "hosts": ["careers.dhl.com"], "search": "https://careers.dhl.com/eu/de/search-results",
               "detail": "^/x$", "adapter": "phenom_widgets", "api": "https://careers.dhl.com/widgets"}
        with mock.patch.dict(os.environ, {"SCRAPLING_EMPLOYERS": json.dumps([row])}):
            with self.assertRaises(ValueError):
                registry()


def catalent_page(jobs, total, embedded=True):
    ddo = {"siteConfig": {"status": "success", "data": {"locale": "en_us"}}}
    if embedded:
        ddo["eagerLoadRefineSearch"] = {"status": 200, "hits": len(jobs), "totalHits": total, "data": {"jobs": jobs}}
    return ('<script>phApp.ddo = ' + json.dumps(ddo) + ';phApp.experimentData = {};</script><script>phApp.pageId = "page19-ds"; '
            'phApp.sessionParams = {"csrfToken":"e4f0cefa51fd493b974057339706bb52"};</script>')


def catalent_hit(ident, title, city, lat, lon, country="Germany"):
    return {"jobId": ident, "jobSeqNo": "CATAUS" + ident + "EXTERNALENUS", "title": title, "city": city, "state": "", "country": country,
            "latitude": str(lat), "longitude": str(lon), "postedDate": "2026-11-10T00:00:00.000+0000", "descriptionTeaser": "Pharma."}


class CatalentTest(unittest.TestCase):
    def crawl(self, page, widgets=None, q="Engineer", location="", radius_km=25):
        Fake.calls, Fake.responses = [], {"widgets": widgets or reply([]), "page": page}
        req = SimpleNamespace(q=q, location=location, radius_km=radius_km, sources=["catalent"])
        with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "catalent"}):
            return crawler.crawl(req, Fake)

    def test_search_goes_through_the_widget_with_the_job_id_in_the_url(self):
        hits = [catalent_hit("0096797", "Process Engineer", "Eberbach", 49.46, 8.99),
                catalent_hit("0096663", "Maintenance Engineer", "Swindon", 51.56, -1.8, country="United Kingdom")]
        result = self.crawl(catalent_page([], total=0), widgets=reply(hits, facets=False))
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual([j["url"] for j in result["jobs"]], ["https://careers.catalent.com/us/en/job/0096797/Process-Engineer"])
        self.assertEqual(result["jobs"][0]["company"], "Catalent")
        self.assertEqual([c[1]["json_body"]["lang"] for c in Fake.calls if "json_body" in c[1]], ["en_us"])

    def test_failing_widget_falls_back_to_the_hits_embedded_in_the_page(self):
        first = [catalent_hit(f"00{n:05d}", f"Engineer {n}", "Eberbach", 49.46, 8.99) for n in range(10)]
        result = self.crawl(catalent_page(first, total=50), widgets=lambda body: {"refineSearch": {"status": 403, "data": None}})
        self.assertEqual(result["sources"][0]["status"], "unsupported")
        self.assertEqual(len(result["jobs"]), 10)
        self.assertIn("eingebettete Seite, Suche fehlgeschlagen", result["sources"][0]["detail"])

    def test_secondary_schorndorf_location_is_kept_in_the_regional_catalog(self):
        # Observed record 0096961: the primary site is Eberbach (outside), the second Schorndorf (inside).
        row = catalent_hit("0096961", "Talent & Leadership Development Manager, Germany", "Eberbach", 49.4668, 8.99016)
        row["multi_location_array"] = [
            {"location": "Eberbach, Baden-Wurttemberg, Germany, 69412", "latlong": {"lat": 49.4668, "lon": 8.99016}},
            {"location": "Schorndorf, Baden-Wurttemberg, Germany, 73614", "latlong": {"lat": 48.80537, "lon": 9.52721}},
        ]
        far = catalent_hit("0097074", "Mitarbeiter Produktion", "Eberbach", 49.4668, 8.99016)
        result = self.crawl(catalent_page([], 0), q="", location="Waiblingen", radius_km=50,
                            widgets=reply([row, far]))
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(len(result["jobs"]), 1)
        job = result["jobs"][0]
        self.assertIn("69412 Eberbach", job["location"])
        self.assertIn("73614 Schorndorf", job["location"])
        self.assertTrue(batch.in_area({**job, "source": "catalent"}))

    def test_multisite_postcode_fallback_and_foreign_primary_site(self):
        row = catalent_hit("0090001", "Engineer", "Beinheim", 48.86, 8.08, country="France")
        row["multi_location_array"] = [
            {"location": "Beinheim, France, 67930", "latlong": {"lat": 48.86, "lon": 8.08}},
            {"location": "Schorndorf, Germany, D-73614", "latlong": {"lat": "NaN", "lon": "Infinity"}},
        ]
        result = self.crawl(catalent_page([], 0), location="Waiblingen", radius_km=50, widgets=reply([row]))
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["location"], "73614 Schorndorf DE")

    def test_unknown_location_is_not_a_radius_match(self):
        row = catalent_hit("0090002", "Engineer", "Unbekanntstadt", "NaN", "Infinity")
        result = self.crawl(catalent_page([], 0), location="Waiblingen", radius_km=50, widgets=reply([row]))
        self.assertEqual(result["jobs"], [])
        self.assertIn("Ort unbekannt 1", result["sources"][0]["detail"])

    def test_expired_job_is_filtered(self):
        row = {**catalent_hit("0090003", "Engineer", "Schorndorf", 48.80537, 9.52721),
               "validThrough": "2000-01-01"}
        result = self.crawl(catalent_page([], 0), widgets=reply([row]))
        self.assertEqual(result["jobs"], [])
        self.assertEqual(result["sources"][0]["filtered"], 1)

    def test_valid_empty_search_does_not_use_unfiltered_embedded_hits(self):
        eager = [catalent_hit("0090004", "Engineer", "Schorndorf", 48.80537, 9.52721)]
        result = self.crawl(catalent_page(eager, 1), widgets=reply([]))
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(result["jobs"], [])
        self.assertIn("0 Treffer (Suche", result["sources"][0]["detail"])

    def test_missing_jobs_is_a_failure_not_an_empty_search(self):
        result = self.crawl(catalent_page([], 0, embedded=False),
                            widgets=lambda body: {"refineSearch": {"status": 200, "totalHits": 0, "data": {}}})
        self.assertEqual(result["sources"][0]["status"], "unsupported")

    def test_all_pages_are_read_and_partial_failures_are_reported(self):
        first = [catalent_hit(f"00{n:05d}", f"Engineer {n}", "Schorndorf", 48.80537, 9.52721) for n in range(10)]
        last = [catalent_hit("0099999", "Engineer last", "Schorndorf", 48.80537, 9.52721)]
        for ending in ("complete", "empty", "repeated", "error"):
            with self.subTest(ending=ending):
                offsets = []

                def widgets(body):
                    offsets.append(body["from"])
                    if body["from"] == 0:
                        return reply(first, total=11)(body)
                    if ending == "error":
                        return {"refineSearch": {"status": 503, "data": None}}
                    return reply(last if ending == "complete" else first if ending == "repeated" else [], total=11)(body)

                result = self.crawl(catalent_page([], 0), widgets=widgets)
                self.assertEqual(offsets, [0, 10])
                self.assertEqual(result["sources"][0]["status"], "done" if ending == "complete" else "incomplete")
                self.assertEqual(len(result["jobs"]), 11 if ending == "complete" else 10)
                if ending != "complete":
                    self.assertIn("unvollständig", result["sources"][0]["detail"])

    def test_failing_widget_without_embedded_hits_is_reported(self):
        result = self.crawl(catalent_page([], total=0, embedded=False),
                            widgets=lambda body: {"refineSearch": {"status": 403, "data": None}})
        self.assertEqual(result["sources"][0]["status"], "unsupported")

    def test_registry_binding(self):
        source = registry()["catalent"]
        self.assertEqual((source.adapter, source.api), ("phenom_widgets", "https://careers.catalent.com/widgets"))


class SessionTransportTest(unittest.TestCase):
    def connection(self, set_cookies=(), status=200, kind="application/json"):
        sent = []

        class Response:
            def __init__(self):
                self.status, self.data = status, b"{}"
                self.msg = SimpleNamespace(get_all=lambda name: list(set_cookies))

            def getheader(self, name, default=None):
                return {"Content-Type": kind}.get(name, default)

            def read(self, n=-1):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

        class Connection:
            def __init__(self, *a): pass
            def request(self, method, path, body=None, headers=None): sent.append((method, path, headers))
            def getresponse(self): return Response()
            def close(self): pass

        return Transport(Budget(), resolve=lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))], connection=Connection), sent

    def test_cookies_are_stored_and_sent_back(self):
        transport, sent = self.connection(["PLAY_SESSION=abc123; Path=/; HttpOnly", "bad name=x", "X=a;b"])
        jar = {}
        transport.get("https://careers.dhl.com/eu/de/search-results", ("careers.dhl.com",), accept_json=True, cookies=jar)
        self.assertEqual(jar, {"PLAY_SESSION": "abc123", "X": "a"})
        transport.get("https://careers.dhl.com/widgets", ("careers.dhl.com",), accept_json=True, json_body={"a": 1}, cookies=jar,
                      extra_headers={"X-CSRF-Token": "tok"})
        self.assertEqual(sent[-1][2]["Cookie"], "PLAY_SESSION=abc123; X=a")
        self.assertEqual(sent[-1][2]["X-CSRF-Token"], "tok")
        self.assertEqual(sent[-1][0], "POST")

    def test_only_listed_headers_and_clean_values_are_allowed(self):
        transport, _ = self.connection()
        for headers in ({"Authorization": "x"}, {"X-CSRF-Token": "a\r\nB: c"}, {"Referer": ""}, {"Origin": "x" * 600}):
            with self.assertRaises(FetchError):
                transport.get("https://careers.dhl.com/widgets", ("careers.dhl.com",), accept_json=True, extra_headers=headers)
        with self.assertRaises(FetchError):
            transport.get("https://careers.dhl.com/robots.txt", ("careers.dhl.com",), robots_request=True, cookies={})

    def test_cookie_jar_is_capped(self):
        jar = {}
        response = SimpleNamespace(msg=SimpleNamespace(get_all=lambda name: [f"c{n}=v" for n in range(40)]))
        store_cookies(jar, response)
        self.assertEqual(len(jar), 20)


if __name__ == "__main__":
    unittest.main()
