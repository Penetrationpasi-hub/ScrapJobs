import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
from rems_adapter import listing
from safe_http import FetchError


def job(href, title, place, stamp="DEU - 29.10.2026"):
    return f'''<div class="starteintragitem"><article class="content-item"><div class="jobentry">
        <div class="jobentrypreline">{stamp}</div><div class="jobadvsummary">
        <h2><a href="{href}">{title}</a></h2><h3>Standort {place}</h3></div></div></article></div>'''


def page(body, title="REMS Recruitment-Portal"):
    return f'''<!DOCTYPE html><html><head><title>{title}</title></head><body>
    <ul class="menu"><li><a href="/stellenangebote">Stellenangebote</a></li><li><a href="/ausbildungsplaetze">Ausbildungspl&#228;tze</a></li>
    <li><a href="/initiativbewerbung">Initiativbewerbung</a></li></ul>
    <article class="projection-page"><header><h1>Stellenangebote</h1></header>{body}</article></body></html>'''


DEU = '<div id="DEU" style="display:none;"><h2>Deutschland</h2>' + "".join([
    job("/ekrmt", "Einkaufssachbearbeiter (m/w/d)", "Hagen"),
    job("/mbs2", "Maschinenbeschicker (m/w/d)", "Waiblingen", "DEU - 21.10.2026"),
    job("/fas", "Fachkraft f&#252;r Arbeitssicherheit, Brand- und Umweltschutz (m/w/d)", "Waiblingen", "DEU - 28.09.2026"),
    job("/minijobber-lager-logistik-m-w-d", "Minijobber Lager / Logistik (m/w/d)", "Waiblingen", "DEU - 19.10.2026"),
]) + "</div>"


class Fake:
    html = ""
    fetched = []

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            raise FetchError("gone", http_status=404)
        if authorize:
            authorize(raw)
        Fake.fetched.append(raw)
        return raw, Fake.html


def run(html, **extra):
    Fake.html, Fake.fetched = html, []
    req = SimpleNamespace(q="", location="", radius_km=25, sources=["rems"], robots_missing_ok=True, **extra)
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "rems"}):
        return crawler.crawl(req, Fake)


class RemsListTest(unittest.TestCase):
    def test_reads_jobs_from_the_list(self):
        result = run(page(DEU))
        self.assertEqual(result["sources"][0]["status"], "done")
        jobs = {j["url"]: j for j in result["jobs"]}
        self.assertEqual(len(jobs), 4)
        first = jobs["https://recruitment.rems.de/ekrmt"]
        self.assertEqual((first["title"], first["company"], first["location"], first["posted"]),
                         ("Einkaufssachbearbeiter (m/w/d)", "REMS", "Hagen", "2026-10-29"))
        self.assertIn("Fachkraft für Arbeitssicherheit", jobs["https://recruitment.rems.de/fas"]["title"])
        self.assertEqual(jobs["https://recruitment.rems.de/fas"]["posted"], "2026-09-28")

    def test_only_the_list_page_is_fetched_and_menu_links_are_ignored(self):
        result = run(page(DEU))
        self.assertEqual(Fake.fetched, ["https://recruitment.rems.de/stellenangebote"])
        urls = [j["url"] for j in result["jobs"]]
        self.assertFalse(any(u.endswith(("initiativbewerbung", "ausbildungsplaetze", "stellenangebote")) for u in urls))

    def test_other_countries_get_a_country_suffix(self):
        body = DEU + '<div id="AUT">' + job("/at1", "Techniker (m/w/d)", "Wien", "AUT - 01.10.2026") + "</div>"
        jobs = {j["url"]: j for j in run(page(body))["jobs"]}
        self.assertEqual(jobs["https://recruitment.rems.de/at1"]["location"], "Wien, AUT")

    def test_links_to_other_hosts_are_rejected(self):
        body = '<div id="DEU">' + job("https://evil.example/abcd", "Fremde Stelle (m/w/d)", "Hagen") + "</div>"
        result = run(page(body))
        self.assertEqual(result["jobs"], [])

    def test_employer_must_be_evidenced_by_the_page_title(self):
        result = run(page(DEU, title="Anderes Portal"))
        self.assertEqual(result["sources"][0]["status"], "unsupported")
        self.assertIn("Seitentitel", result["sources"][0]["detail"])

    def test_broken_entries_are_counted_not_emitted(self):
        broken = '<div id="DEU"><div class="jobentry"><div class="jobentrypreline">DEU - 01.01.2026</div><h3>Standort X</h3></div></div>'
        result = run(page(broken))
        self.assertEqual(result["jobs"], [])
        self.assertEqual(result["sources"][0]["filtered"], 1)

    def test_listing_requires_title(self):
        with self.assertRaises(FetchError):
            listing("<html><title>x</title></html>", "https://recruitment.rems.de/stellenangebote")


if __name__ == "__main__":
    unittest.main()
