import os
import unittest
from types import SimpleNamespace
from unittest import mock

import crawler
from personio_adapter import positions
from safe_http import Budget, FetchError, Transport
from sources import registry

API = "https://mpire.jobs.personio.de/xml"


def position(ident, name, company="RIVA GmbH Engineering", office="Backnang Lerchenäcker", created="2026-09-21T08:27:29+00:00", extra=""):
    return f"""<position>
<id>{ident}</id>
<subcompany>{company}</subcompany>
<office>{office}</office>{extra}
<department>RE Ausbildung Kaufmännisch</department>
<recruitingCategory>Azubi kaufmännisch</recruitingCategory>
<name>{name}</name>
<jobDescriptions><jobDescription><name>Das sind wir </name><value><![CDATA[ <strong style="x">Volltext &amp; Bilder</strong> ]]></value></jobDescription></jobDescriptions>
<employmentType>trainee</employmentType>
<createdAt>{created}</createdAt>
</position>
"""


FEED = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<workzag-jobs>\n" + "".join([
    position(2804953, "Ausbildung zum Industriekaufmann (m/w/d) 2027"),
    position(2670131, "SPS-Programmierer/Softwareentwickler für Brennstoffzellen (m/w/d)", company="RIVA Power Systems GmbH &amp; Co. KG"),
    # ungültiges XML, wie es im Browser-Baum erscheint: rohes "&"
    position(2706289, "Vertriebsmitarbeiter im Außendienst (m/w/d) – LED-Beleuchtung / Lichttechnik – DACH-Region",
             company="LIGHTS 4 Europe GmbH & Co. KG"),
    position(2579051, "Initiativbewerbung (m/w/d) – RIVA-Gruppe", company="Mpire GmbH",
             extra="<additionalOffices><office>Backnang Gerberpark</office><office>Kirchberg</office></additionalOffices>"),
    position(2855152, "Digital Marketing Manager (m/w/d) – Website, Performance & Leadgenerierung", company="Mpire GmbH",
             created="2026-10-22T11:11:06+00:00"),
]) + "</workzag-jobs>")


class Fake:
    feed = FEED
    fetched = []

    def __init__(self, budget):
        self.budget, self.last = budget, {}

    def get(self, raw, hosts, authorize=None, **kw):
        if raw.endswith("/robots.txt"):
            raise FetchError("gone", http_status=404)
        if authorize:
            authorize(raw)
        Fake.fetched.append((raw, kw))
        return raw, Fake.feed


def run(feed=FEED, q="", **extra):
    Fake.feed, Fake.fetched = feed, []
    req = SimpleNamespace(q=q, location="", radius_km=25, sources=["riva"], robots_missing_ok=True, **extra)
    with mock.patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "riva"}):
        return crawler.crawl(req, Fake)


class PersonioTest(unittest.TestCase):
    def test_reads_jobs_from_the_xml_feed(self):
        result = run()
        self.assertEqual(result["sources"][0]["status"], "done")
        jobs = {j["url"]: j for j in result["jobs"]}
        first = jobs["https://mpire.jobs.personio.de/job/2804953"]
        self.assertEqual(first["title"], "Ausbildung zum Industriekaufmann (m/w/d) 2027")
        self.assertEqual(first["company"], "RIVA GmbH Engineering")
        self.assertEqual(first["location"], "Backnang Lerchenäcker")
        self.assertEqual(first["posted"], "2026-09-21")

    def test_unsolicited_application_is_not_a_vacancy(self):
        result = run()
        self.assertNotIn("https://mpire.jobs.personio.de/job/2579051", [j["url"] for j in result["jobs"]])
        self.assertEqual(result["sources"][0]["filtered"], 1)
        self.assertEqual(len(result["jobs"]), 4)

    def test_ampersands_are_handled_escaped_and_bare(self):
        companies = {j["company"] for j in run()["jobs"]}
        self.assertIn("RIVA Power Systems GmbH & Co. KG", companies)
        self.assertIn("LIGHTS 4 Europe GmbH & Co. KG", companies)
        titles = {j["title"] for j in run()["jobs"]}
        self.assertIn("Digital Marketing Manager (m/w/d) – Website, Performance & Leadgenerierung", titles)

    def test_descriptions_are_not_published(self):
        for job in run()["jobs"]:
            self.assertFalse(job["description"])

    def test_only_the_feed_is_fetched_as_xml(self):
        run()
        self.assertEqual(len(Fake.fetched), 1)
        self.assertEqual(Fake.fetched[0][0], API)
        self.assertTrue(Fake.fetched[0][1].get("accept_xml"))

    def test_additional_offices_are_joined(self):
        rows = positions(FEED)
        initiative = [r for r in rows if r["id"] == "2579051"][0]
        self.assertEqual(initiative["place"], "Backnang Lerchenäcker, Backnang Gerberpark, Kirchberg")

    def test_doctype_and_entities_are_rejected(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workzag-jobs><position><id>1</id></position></workzag-jobs>'
        with self.assertRaises(FetchError):
            positions(bomb)

    def test_foreign_or_broken_documents_are_reported_not_ignored(self):
        for text in ("<html><body>Nein</body></html>", "<workzag-jobs><position>", "<other/>"):
            result = run(text)
            self.assertEqual(result["sources"][0]["status"], "unsupported", text)
            self.assertTrue(result["sources"][0]["detail"])

    def test_job_ids_must_be_numeric(self):
        feed = FEED.replace("<id>2804953</id>", "<id>../evil</id>")
        result = run(feed)
        self.assertNotIn("evil", " ".join(j["url"] for j in result["jobs"]))

    def test_registry_binds_the_adapter_to_the_tenant_feed(self):
        source = registry()["riva"]
        self.assertEqual((source.adapter, source.api), ("personio", API))


class XmlTransportTest(unittest.TestCase):
    def fetch(self, kind, accept_xml=True, body=b"<workzag-jobs/>"):
        class Response:
            status = 200

            def __init__(self):
                self.data = body

            def getheader(self, name, default=None):
                return {"Content-Type": kind}.get(name, default)

            def read(self, n=-1):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

        class Connection:
            sent = []

            def __init__(self, *a): pass

            def request(self, method, path, body=None, headers=None):
                Connection.sent.append((method, path, headers))

            def getresponse(self): return Response()
            def close(self): pass

        transport = Transport(Budget(), resolve=lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 443))], connection=Connection)
        text = transport.get(API, ("mpire.jobs.personio.de",), accept_xml=accept_xml)[1]
        return text, Connection.sent[-1]

    def test_xml_content_types_are_accepted_with_xml_accept_header(self):
        for kind in ("application/xml", "text/xml; charset=utf-8"):
            text, (method, path, headers) = self.fetch(kind)
            self.assertEqual((method, path, headers["Accept"]), ("GET", "/xml", "application/xml,text/xml"))

    def test_html_is_rejected_for_xml_requests(self):
        with self.assertRaises(FetchError) as caught:
            self.fetch("text/html")
        self.assertEqual(caught.exception.code, "unsupported")

    def test_xml_cannot_be_combined_with_json_or_robots(self):
        transport = Transport(Budget())
        for options in ({"accept_json": True}, {"robots_request": True}, {"json_body": {"a": 1}}):
            with self.assertRaises(FetchError):
                transport.get(API, ("mpire.jobs.personio.de",), accept_xml=True, **options)


if __name__ == "__main__":
    unittest.main()
