import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
from dvinci_adapter import publications
from safe_http import FetchError

BASE = "https://jobs.wir-machen-druck.de/de/jobs/"


def entry(ident, slug, title, location, company="WIRmachenDRUCK GmbH", created="2026-11-06T06:55:25.689Z", **extra):
    return {"id": ident, "language": "de", "position": title, "pageTitle": title,
            "jobPublicationURL": f"{BASE}{ident}/{slug}", "endDate": None,
            "jobOpening": {"id": ident - 7, "name": title, "location": location, "createdDate": created,
                           "company": {"id": 2, "name": company}}, **extra}


ROWS = [
    entry(30213, "business-controller-mwd-remote-deutschlandweit", "Business Controller (m/w/d) - remote deutschlandweit",
          "Backnang, Baden-Württemberg, deutschlandweit", created="2025-01-09T12:47:34.080Z"),
    entry(30238, "mitarbeiter-weiterverarbeitung-produktion-digitaldruck-mwd-100-standort-baar-schweiz",
          "Mitarbeiter Weiterverarbeitung Produktion Digitaldruck (m/w/d)", "Baar, Schweiz", company="WIRmachenDRUCK AG"),
    entry(30304, "sachbearbeiter-kreditorenbuchhaltung", "Sachbearbeiter Kreditorenbuchhaltung", "Backnang, Baden-Württemberg"),
    {**entry(30001, "abgelaufen", "Alte Stelle (m/w/d)", "Backnang"), "endDate": "2020-01-01T00:00:00Z"},
    {"id": 5, "position": "Ohne Link"},
]
PAGE = ("<!doctype html><html><head><title>Stellenangebote</title><script nonce=\"x\" type=\"text/javascript\">\n"
        "      var DvinciData = " + json.dumps({"jobPublications": ROWS}, ensure_ascii=False) + "\n    </script></head>"
        "<body><p>Keine passende Stelle? <a href=\"https://jobs.wir-machen-druck.de/de/jobs/4/intro\">Initiativbewerbung</a>!</p></body></html>")


class Fake:
    page = PAGE
    fetched = []

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            raise FetchError("gone", http_status=404)
        if authorize:
            authorize(raw)
        Fake.fetched.append(raw)
        return raw, self.page


def run(page=PAGE, q="", **extra):
    Fake.page = page
    Fake.fetched = []
    req = SimpleNamespace(q=q, location="", radius_km=25, sources=["wirmachendruck"], **extra)
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "wirmachendruck"}):
        return crawler.crawl(req, Fake)


class DvinciTest(unittest.TestCase):
    def test_reads_all_valid_publications_from_the_list_page(self):
        result = run(robots_missing_ok=True)
        titles = [job["title"] for job in result["jobs"]]
        self.assertEqual(len(titles), 3)
        self.assertEqual(result["sources"][0]["status"], "done")
        self.assertEqual(result["sources"][0]["filtered"], 2)  # abgelaufen + ohne Link
        job = result["jobs"][0]
        self.assertEqual(job["company"], "WIRmachenDRUCK GmbH")
        self.assertEqual(job["location"], "Backnang, Baden-Württemberg, deutschlandweit")
        self.assertEqual(job["posted"], "2025-01-09")
        self.assertEqual(job["url"], BASE + "30213/business-controller-mwd-remote-deutschlandweit")
        self.assertEqual({j["company"] for j in result["jobs"]}, {"WIRmachenDRUCK GmbH", "WIRmachenDRUCK AG"})

    def test_initiative_application_page_is_never_a_job(self):
        urls = [job["url"] for job in run(robots_missing_ok=True)["jobs"]]
        self.assertFalse(any("/4/intro" in url for url in urls))

    def test_only_the_list_page_is_fetched(self):
        run(robots_missing_ok=True)
        self.assertEqual(Fake.fetched, ["https://jobs.wir-machen-druck.de/de/jobs"])

    def test_missing_robots_stays_strict_without_the_catalog_flag(self):
        self.assertEqual(run()["sources"][0]["status"], "robots_unavailable")

    def test_job_url_must_stay_on_the_employer_host(self):
        rows = [{**ROWS[0], "jobPublicationURL": "https://evil.example/de/jobs/30213/x"}]
        page = PAGE.replace(json.dumps({"jobPublications": ROWS}, ensure_ascii=False),
                            json.dumps({"jobPublications": rows}, ensure_ascii=False))
        self.assertEqual(run(page, robots_missing_ok=True)["jobs"], [])

    def test_page_without_data_is_reported_not_empty(self):
        result = run("<html><body>Kein Datenblock</body></html>", robots_missing_ok=True)
        self.assertEqual(result["sources"][0]["status"], "unsupported")
        self.assertEqual(result["sources"][0]["detail"], "DvinciData nicht gefunden")

    def test_publications_parser_rejects_broken_json(self):
        with self.assertRaises(FetchError):
            publications("var DvinciData = {nicht json")


if __name__ == "__main__":
    unittest.main()
