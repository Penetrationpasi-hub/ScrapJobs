"""d&b audiotechnik: Anzeigen kommen aus dem öffentlichen Workday-Portal (die Liste auf dbaudio.com ist JavaScript)."""
import json
import unittest
from types import SimpleNamespace

from employer_adapters import adapter_jobs
from sources import registry

BOARD = "https://dbaudio.wd103.myworkdayjobs.com/de-DE/dbaudiotechnik-careers-de"


def posting(raw, company, title):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "url": raw, "title": title, "hiringOrganization": {"name": company},
        "description": "Du denkst Sicherheit ganzheitlich und schützt kritische Systeme, Anwendungen und Daten.",
        "jobLocation": {"address": {"addressLocality": "Headquarters (Backnang, Eugen-Adolff-Straße)"}},
        "datePosted": "2026-11-03"}) + "</script>"


class DbAudioTest(unittest.TestCase):
    source = registry()["db_audiotechnik"]

    def run_adapter(self, respond):
        calls, report = [], {"filtered": 0}

        def get(raw, source, **options):
            calls.append((raw, options))
            result = respond(raw, options)
            return raw, result if isinstance(result, str) else json.dumps(result)

        jobs = list(adapter_jobs(self.source, SimpleNamespace(q="", location="", max_details=10), get, report))
        return jobs, report, calls

    def test_config_points_at_the_workday_board(self):
        self.assertEqual(self.source.adapter, "workday")
        self.assertEqual(self.source.hosts, ("dbaudio.wd103.myworkdayjobs.com",))
        self.assertTrue(self.source.api.endswith("/wday/cxs/dbaudio/dbaudiotechnik-careers-de/jobs"))

    def test_workday_search_and_real_detail(self):
        good = "/job/Headquarters-Backnang-Eugen-Adolff-Strae/IT-Security-Specialist--w-m-d-_REQ_2026_00000180"

        def respond(raw, options):
            if options.get("accept_json"):
                return {"jobPostings": [{"externalPath": good}, {"externalPath": "https://evil.test/job/1"}]}
            return posting(raw, "d&b audiotechnik GmbH & Co. KG", "IT Security Specialist (w/m/d)")

        jobs, report, calls = self.run_adapter(respond)
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["title"], jobs[0]["company"]), ("IT Security Specialist (w/m/d)", "d&b audiotechnik GmbH & Co. KG"))
        self.assertEqual(jobs[0]["url"], BOARD + good)
        self.assertEqual(report["filtered"], 0)

    def test_foreign_company_is_filtered(self):
        def respond(raw, options):
            if options.get("accept_json"):
                return {"jobPostings": [{"externalPath": "/job/Backnang/Servicetechniker_REQ_1"}]}
            return posting(raw, "Andere GmbH", "Servicetechniker (m/w/d)")

        jobs, report, _ = self.run_adapter(respond)
        self.assertEqual(jobs, [])
        self.assertEqual(report["filtered"], 1)


if __name__ == "__main__":
    unittest.main()
