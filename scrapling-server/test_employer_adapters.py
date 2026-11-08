"""Small offline fixtures model the inspected employer HTML/public JSON formats."""
import json
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from crawler import crawl
from employer_adapters import adapter_jobs, json_document
from extraction import extract
from safe_http import Budget, FetchError, Transport
from sources import registry


def posting(raw, company, title="Software Entwickler (m/w/d)"):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "url": raw, "title": title,
        "hiringOrganization": {"name": company},
        "description": "Softwareentwicklung und technische Aufgaben.",
    }) + "</script>"


class EmployerFormats(unittest.TestCase):
    def run_adapter(self, key, responder, query="Software"):
        calls, report = [], {"filtered": 0}
        def get(raw, source, **options):
            calls.append((raw, options))
            result = responder(raw, options)
            if isinstance(result, Exception):
                raise result
            return raw, result if isinstance(result, str) else json.dumps(result)
        jobs = list(adapter_jobs(registry()[key], SimpleNamespace(q=query, location=""), get, report))
        return jobs, report, calls

    def test_workday_uses_fixed_search_and_validates_real_detail(self):
        def respond(raw, options):
            if options.get("accept_json"):
                self.assertEqual(options["json_body"]["searchText"], "Software")
                self.assertEqual(options["json_body"]["limit"], 20)
                return {"jobPostings": [{"title": "Software", "externalPath": "/job/Winnenden/Software_JR1"},
                                        {"title": "Other", "externalPath": "https://evil.test/job/1"}]}
            return posting(raw, "Techtronic Industries ELC GmbH")
        jobs, report, calls = self.run_adapter("tti", respond)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(report["filtered"], 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0].endswith("/wday/cxs/ttiemea/TTI/jobs"))
        self.assertEqual(jobs[0]["company"], "Techtronic Industries ELC GmbH")

    def test_workday_rejects_loading_shell_malformed_api_and_wrong_employer(self):
        for payload in ({}, {"jobPostings": "loading"}, {"jobPostings": [None]}):
            with self.assertRaises(FetchError):
                self.run_adapter("tti", lambda raw, options: payload)
        jobs, report, _ = self.run_adapter("tti", lambda raw, options:
            {"jobPostings": [{"externalPath": "/job/Winnenden/Software_JR1"}]} if options else posting(raw, "Other Company"))
        self.assertFalse(jobs)
        self.assertEqual(report["filtered"], 1)

    def test_myjobboard_requires_single_matching_public_job_and_employer(self):
        ident = "63aec2bcfb5a9f4266d751d3"
        actual = {"id": ident, "title": "Software Entwickler", "tenant": "stadtwerke-waiblingen",
                  "accessibilityLevel": "Public", "hiringOrganization": {"name": "Stadtwerke Waiblingen GmbH"},
                  "description": "Softwareentwicklung", "postalAddress": {"addressLocality": "Waiblingen"},
                  "publishUntil": "2099-12-31"}
        def respond(raw, options):
            return {"jobs": [actual]}
        jobs, _, calls = self.run_adapter("stadtwerke_waiblingen", respond)
        self.assertEqual(len(jobs), 1)
        self.assertIn("/Stellenangebote/" + ident, jobs[0]["url"])
        self.assertEqual(jobs[0]["location"], "Waiblingen")
        self.assertEqual(len(calls), 2)
        for key, bad in (("tenant", "other"), ("accessibilityLevel", "Private"),
                         ("hiringOrganization", {"name": "Other Company"}), ("publishUntil", "2020-01-01")):
            previous = actual[key]
            actual[key] = bad
            self.assertFalse(self.run_adapter("stadtwerke_waiblingen", respond)[0])
            actual[key] = previous

    def test_myjobboard_rejects_list_in_place_of_detail(self):
        ident = "63aec2bcfb5a9f4266d751d3"
        def respond(raw, options):
            return {"jobs": [{"id": ident}]} if not raw.endswith(ident) else {"jobs": [{"id": ident}, {"id": ident}]}
        self.assertFalse(self.run_adapter("stadtwerke_waiblingen", respond)[0])

    def test_easyhr_proves_official_board_binding_customer_and_online_status(self):
        board = "3e591c90-d9bf-4ea5-ae09-9395cd2e322d"
        ident = "0049bb87-7a92-424e-b783-bcc1bc90471d"
        detail = {"id": ident, "customer_id": board, "online": True,
                  "title": "Software Entwickler", "location": "Schorndorf", "editor": "<p>Softwareentwicklung</p>"}
        def respond(raw, options):
            if not options:
                return '<meta property="og:site_name" content="Dusyma"><iframe src="https://jobboard.easyhr.io/?board[]=' + board + '"></iframe>'
            return detail if "/position?" in raw else [{"id": ident, "title": detail["title"]}]
        jobs, _, calls = self.run_adapter("dusyma", respond)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Dusyma")
        self.assertEqual(jobs[0]["location"], "Schorndorf")
        self.assertEqual(len(calls), 3)
        for field, bad in (("customer_id", "other"), ("online", False), ("id", "other")):
            old = detail[field]
            detail[field] = bad
            self.assertFalse(self.run_adapter("dusyma", respond)[0])
            detail[field] = old
        with self.assertRaises(FetchError):
            self.run_adapter("dusyma", lambda raw, options: '<meta property="og:site_name" content="Other">')

    def test_hahn_uses_two_public_categories_and_rejects_foreign_urls_and_employers(self):
        raw_job = "https://ats.sopea-hr.com/ats/JobAd?Job=0384257169"
        def respond(raw, options):
            if options:
                return [{"VacancyName": "Software", "VacancyUrl": raw_job},
                        {"VacancyName": "Software", "VacancyUrl": "https://evil.test/ats/JobAd?Job=0384257169"}]
            return posting(raw, "Hahn Automobile GmbH + Co. KG")
        jobs, _, calls = self.run_adapter("hahn_automobile", respond)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(calls), 3)
        self.assertFalse(any("6dbeb200" in raw for raw, _ in calls))
        self.assertFalse(self.run_adapter("hahn_automobile", lambda raw, options:
            [{"VacancyUrl": raw_job}] if options else posting(raw, "Other Company"))[0])

    def test_removed_workday_job_does_not_stop_remaining_details(self):
        def respond(raw, options):
            if options:
                return {"jobPostings": [{"externalPath": "/job/Gone_JR1"}, {"externalPath": "/job/Software_JR2"}]}
            return FetchError("gone") if "Gone" in raw else posting(raw, "Techtronic Industries ELC GmbH")
        jobs, report, _ = self.run_adapter("tti", respond)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(report["filtered"], 1)

    def test_benz_separates_nested_roles_and_omits_unsolicited_applications(self):
        html = '''<meta name="DC.Publisher" content="Gotthilf Benz Turngerätefabrik GmbH + Co. KG">
          <div class="typo"><h2>Software Entwickler (m/w/d)</h2><h5>Standort: Winnenden</h5>
          <p>Softwareentwicklung und technische Aufgaben in einem erfahrenen Team. Wir suchen konkrete Verstärkung für die Produktentwicklung.</p>
          <div><h2>Lagerhelfer (m/w/d)</h2><h5>Standort: Schorndorf</h5>
          <p>Lagerarbeit und Verpackung, Warenannahme und Kommissionierung. Eigenständige Abläufe und Mitarbeit in unserem Logistikteam.</p></div>
          <h2>Initiative Bewerbung bei BENZ (m/w/d)</h2><p>Software und Logistik</p></div>'''
        jobs, _, _ = self.run_adapter("benz_sport", lambda raw, options: html)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "Winnenden")
        self.assertNotIn("Lagerarbeit", jobs[0]["description"])
        all_jobs = self.run_adapter("benz_sport", lambda raw, options: html, query="")[0]
        self.assertEqual(len(all_jobs), 2)
        self.assertEqual(len({job["url"] for job in all_jobs}), 2)
        self.assertTrue(all("#:~:text=" in job["url"] for job in all_jobs))
        with self.assertRaises(FetchError):
            self.run_adapter("benz_sport", lambda raw, options: html.replace("Gotthilf Benz", "Other"))

    def test_eisenmann_proves_publisher_and_individual_accordion_content(self):
        html = '''<div class="accordion"><h4 class="trigger">Software Entwickler (m/w/d) für Süddeutschland</h4>
        <div class="toggle_container"><p>Softwareentwicklung und technische Aufgaben für unseren Bahnbetrieb.
        Eigenverantwortliches Arbeiten in erfahrenen Teams mit strukturierter Weiterbildung und langfristiger Perspektive.</p></div></div>
        <p>Eisenmann Personal-Service GmbH</p>'''
        jobs, _, _ = self.run_adapter("eisenmann", lambda raw, options: html)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "Eisenmann Personal-Service GmbH")
        self.assertEqual(jobs[0]["location"], "für Süddeutschland")

    def test_html_fields_are_evidence_not_guessed_from_label_or_url(self):
        riani = registry()["riani"]
        raw = "https://www.riani.com/de_en/Company/Karriere/Designer-GN-Strick"
        html = '<meta property="og:title" content="Designer (GN) Strick"><meta property="og:site_name" content="RIANI"><div class="cms-element-text"><h4>Am Standort Schorndorf</h4><p>Strickkollektionen entwickeln</p></div>'
        self.assertEqual(extract(html, raw, riani)["company"], "RIANI")
        self.assertIsNone(extract(html.replace('content="RIANI"', 'content="Other"'), raw, riani))
        awrm = registry()["awrm"]
        raw = "https://www.abfallwirtschaft-rems-murr.de/unsere-awrm/jobs/detail/verwaltung"
        html = '<meta property="og:title" content="Sachbearbeiter (m/w/d)"><div class="news-text-wrap"><p><strong>Die Abfallwirtschaft Rems-Murr AöR sucht Verstärkung.</strong></p></div>'
        self.assertEqual(extract(html, raw, awrm)["company"], "Abfallwirtschaft Rems-Murr AöR")
        self.assertIsNone(extract(html.replace("Abfallwirtschaft Rems-Murr AöR", "Unbekannte Firma"), raw, awrm))


class APITransport(unittest.TestCase):
    def response(self, *, status=200, kind="application/json", body=b'{"ok":true}'):
        class Response:
            def __init__(self):
                self.status = status
                self.remaining = body
            def getheader(self, name, default=None):
                return {"Content-Type": kind, "Content-Encoding": "identity",
                        "Location": "https://127.0.0.1/private"}.get(name, default)
            def read(self, size):
                value, self.remaining = self.remaining[:size], self.remaining[size:]
                return value
        return Response

    def transport(self, response, ip="8.8.8.8"):
        calls = []
        class Connection:
            def __init__(self, *args): pass
            def request(self, method, path, **options): calls.append((method, path, options))
            def getresponse(self): return response()
            def close(self): pass
        resolve = lambda *args, **kwargs: [(None, None, None, None, (ip, 443))]
        return Transport(Budget(), resolve=resolve, connection=Connection), calls

    def test_api_post_is_pinned_authorized_budgeted_and_json_only(self):
        transport, calls = self.transport(self.response())
        checked = []
        transport.get("https://jobs.test/search", ("jobs.test",), authorize=checked.append,
                      accept_json=True, json_body={"searchText": "Software & more"})
        self.assertEqual(checked, ["https://jobs.test/search"])
        self.assertEqual(transport.budget.remaining, 39)
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][2]["headers"]["Accept-Encoding"], "identity")
        self.assertEqual(json.loads(calls[0][2]["body"])["searchText"], "Software & more")

    def test_api_does_not_follow_redirect_or_accept_html_or_private_target(self):
        for response, ip in ((self.response(status=302), "8.8.8.8"),
                             (self.response(kind="text/html"), "8.8.8.8"),
                             (self.response(), "127.0.0.1")):
            transport, calls = self.transport(response, ip)
            with self.assertRaises(FetchError):
                transport.get("https://jobs.test/search", ("jobs.test",), accept_json=True, json_body={})
            self.assertLessEqual(len(calls), 1)

    def test_large_post_rejected_without_request(self):
        transport, calls = self.transport(self.response())
        with self.assertRaises(FetchError):
            transport.get("https://jobs.test/search", ("jobs.test",), accept_json=True,
                          json_body={"q": "x" * 5000})
        self.assertFalse(calls)

    def test_robots_still_controls_workday_post(self):
        requested = []
        class FakeTransport:
            def __init__(self, budget): self.budget, self.last = budget, {}
            def get(self, raw, hosts, authorize=None, **options):
                if authorize: authorize(raw)
                self.budget.claim()
                requested.append(raw)
                return raw, "User-agent: *\nDisallow: /wday/cxs/"
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "tti"}):
            result = crawl(SimpleNamespace(sources=["tti"], q="Software", location=""), FakeTransport)
        self.assertEqual(result["sources"][0]["status"], "robots_denied")
        self.assertTrue(all(raw.endswith("/robots.txt") for raw in requested))
        self.assertEqual(result["documents"], 1)

    def test_global_30_jobs_cap_prevents_fourth_adapter_requests(self):
        template = registry()["tti"]
        sources = {key: replace(template, key=key, label=key, hosts=(key + ".jobs.test",),
                               search=f"https://{key}.jobs.test/de-DE/TTI",
                               api=f"https://{key}.jobs.test/wday/cxs/ttiemea/TTI/jobs")
                   for key in ("one", "two", "three", "four")}
        requested = []
        class FakeTransport:
            def __init__(self, budget): self.budget, self.last = budget, {}
            def get(self, raw, hosts, authorize=None, **options):
                if authorize: authorize(raw)
                self.budget.claim()
                requested.append(raw)
                if raw.endswith("robots.txt"):
                    return raw, "User-agent: *\nAllow: /"
                if options:
                    return raw, json.dumps({"jobPostings": [{"externalPath": f"/job/Software_JR{i}"} for i in range(10)]})
                return raw, posting(raw, "Techtronic Industries ELC GmbH")
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}), patch("crawler.registry", return_value=sources):
            result = crawl(SimpleNamespace(sources=list(sources), q="Software", location=""), FakeTransport)
        self.assertEqual(len(result["jobs"]), 30)
        self.assertLessEqual(result["documents"], 40)
        self.assertFalse(any("four.jobs.test" in raw for raw in requested))
        self.assertEqual(result["sources"][-1]["status"], "result_limit")
