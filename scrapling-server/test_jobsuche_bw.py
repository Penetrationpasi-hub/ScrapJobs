"""Offline checks for jobsucheBW (Nussbaum Medien). Fixtures mirror the observed public pages."""
import json
import os
import unittest
from unittest.mock import patch

from extraction import discovery, extract
from sources import registry, approved_sources

OWN = "https://www.jobsuche-bw.de/jobs/16427094/Verkaufstalent_(m_w_d)_Waldbronn__Bretten__Bruchs"
PARTNER = "https://www.jobsuche-bw.de/jobs/IDA-2978148/Elektriker_in_(m_w_d)_Fridingen_an_der_Donau_Elek"


def page(**changes):
    posting = {"@context": "http://schema.org", "@type": "JobPosting", "title": "Verkaufstalent (m/w/d)",
               "datePosted": "2026-10-30", "directApply": True, "validThrough": "2099-11-29",
               "description": "<h1> Verkaufstalent (m/w/d)</h1><h2> WERDE TEIL UNSERES TEAMS</h2><p> In Voll- und Teilzeit "
                              "sowie Minijob. <br/> Quereinsteiger willkommen!</p><ins> VERKAUFSTALENTE <prt-nobr> (m/w/d) </prt-nobr></ins>",
               "hiringOrganization": {"@type": "Organization", "name": "Bäckerei Thollembeek GmbH & Co. KG"},
               "employmentType": "FULL_TIME",
               "jobLocation": [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Waldbronn",
                                                              "postalCode": "76337", "addressCountry": "DE",
                                                              "addressRegion": "Baden-Württemberg", "streetAddress": ""}},
                               {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Bretten",
                                                              "postalCode": "75015", "addressCountry": "DE",
                                                              "addressRegion": "Baden-Württemberg", "streetAddress": ""}}]}
    posting.update(changes)
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": []}
    return "".join('<script type="application/ld+json">' + json.dumps(x) + "</script>" for x in (crumbs, posting))


class JobsucheBW(unittest.TestCase):
    def setUp(self):
        self.source = registry()["jobsuche_bw"]

    def test_catalog_entry_and_search_template(self):
        self.assertTrue(self.source.available)
        self.assertEqual(self.source.hosts, ("www.jobsuche-bw.de",))
        self.assertEqual(self.source.max_pages, 1)
        self.assertEqual(self.source.start("Elektriker & Monteur", "Waiblingen"),
                         "https://www.jobsuche-bw.de/suchergebnis/?fulltext=Elektriker%20%26%20Monteur")

    def test_discovery_keeps_own_and_partner_ids_but_no_other_links(self):
        html = ('<a data-testid="qa-hitzone" href="https://www.jobsuche-bw.de/jobs/SDE-132380/Teamleitung_Pflege_(m_w_i)_Gunzenhausen_Stiftung_/">Pflege</a>'
                '<a data-testid="enhanced-link" href="https://www.jobsuche-bw.de/jobs/SDE-132380/Teamleitung_Pflege_(m_w_i)_Gunzenhausen_Stiftung_/">dup</a>'
                '<a href="/jobs/16427094/Verkaufstalent_(m_w_d)_Waldbronn__Bretten__Bruchs/">own</a>'
                '<a href="/jobs/IDA-2978148/Elektriker_in_(m_w_d)_Fridingen_an_der_Donau_Elek/">partner</a>'
                '<a href="/suchergebnis/www.google.de/test">x</a><a href="/stellenangebote/pflege/?seite=2">Mehr laden</a>'
                '<a href="/jobs/">alle</a><a href="/bewerbung/IDA-2978148/">bewerben</a><a href="/job/drucken/16427094">drucken</a>'
                '<a href="https://dxl6houvklhzf.cloudfront.net/public/jobs/IDA-2978148/-home-nbm-2289162-2289162.pdf">pdf</a>'
                '<a href="https://evil.test/jobs/16427094/x">evil</a>')
        links, following = discovery(html, "https://www.jobsuche-bw.de/suchergebnis/?fulltext=Pflege", self.source, "Pflege")
        self.assertEqual(links, [
            "https://www.jobsuche-bw.de/jobs/SDE-132380/Teamleitung_Pflege_(m_w_i)_Gunzenhausen_Stiftung_",
            "https://www.jobsuche-bw.de/jobs/16427094/Verkaufstalent_(m_w_d)_Waldbronn__Bretten__Bruchs",
            "https://www.jobsuche-bw.de/jobs/IDA-2978148/Elektriker_in_(m_w_d)_Fridingen_an_der_Donau_Elek"])
        self.assertIsNone(following)

    def test_real_employer_not_the_portal_and_clean_description(self):
        job = extract(page(), OWN + "/", self.source, "Verkauf")
        self.assertEqual(job["company"], "Bäckerei Thollembeek GmbH & Co. KG")
        self.assertEqual(job["title"], "Verkaufstalent (m/w/d)")
        self.assertEqual(job["posted"], "2026-10-30")
        self.assertEqual(job["url"], OWN)
        self.assertIn("76337 Waldbronn", job["location"])
        self.assertIn("75015 Bretten", job["location"])
        self.assertNotIn("<", job["description"])
        self.assertIn("Quereinsteiger willkommen", job["description"])

    def test_partner_ad_with_utc_timestamps(self):
        html = page(title="Elektriker/in (m/w/d)", datePosted="2026-11-04T23:00:00+00:00",
                    validThrough="2099-12-05T22:59:00+00:00",
                    hiringOrganization={"@type": "Organization", "name": "Elektro Beier GmbH"},
                    jobLocation=[{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Fridingen an der Donau",
                                                                "postalCode": "78567", "addressCountry": "DE"}}],
                    description="<p>Elektro Beier GmbH in 78567 Fridingen sucht <b>Elektriker/in (m/w/d)</b></p>")
        job = extract(html, PARTNER, self.source, "Elektriker")
        self.assertEqual(job["company"], "Elektro Beier GmbH")
        self.assertEqual(job["posted"], "2026-11-04")
        self.assertEqual(job["location"], "78567 Fridingen an der Donau DE")

    def test_observed_detail_page_with_testid_script_and_unencoded_umlauts(self):
        """JSON-LD copied from the public ad 16427091; the script tag carries data-testid, title has a raw '&'."""
        ld = {"@context": "http://schema.org", "@type": "JobPosting", "title": "Bäcker & Konditor (m/w/d)",
              "datePosted": "2026-10-30", "directApply": True, "validThrough": "2099-11-29",
              "description": "<h1> Bäcker &amp; Konditor (m/w/d)</h1><h2> WERDE TEIL UNSERES TEAMS</h2><p> In Voll- und Teilzeit sowie "
                             "Minijob. <br/> Quereinsteiger willkommen!</p><ins> BÄCKER &amp; KONDITOREN <prt-nobr>  (m/w/d) </prt-nobr></ins>"
                             "<p> Jetzt bewerben! <br/> jobs @thollembeek.de <br/> 07252-9445-10</p>",
              "hiringOrganization": {"@type": "Organization", "name": "Bäckerei Thollembeek GmbH & Co. KG",
                                     "logo": "https://logos.jobstatic.de/g4j/logo/472469.png"},
              "employmentType": "FULL_TIME",
              "jobLocation": [{"@type": "Place", "geo": {"@type": "GeoCoordinates", "latitude": 49.03666, "longitude": 8.70764},
                               "address": {"@type": "PostalAddress", "addressLocality": "Bretten", "postalCode": "75015",
                                           "addressCountry": "DE", "addressRegion": "Baden-Württemberg", "streetAddress": ""}}],
              "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
                             "value": {"@type": "QuantitativeValue", "minValue": 0.0, "maxValue": 0.0, "unitText": "YEAR", "value": 0.0}}}
        html = ('<html><body><iframe src="/api/jobs/iframe/?jobId=16427091"></iframe>'
                '<script type="application/ld+json" data-testid="qa-googleForJobs">' + json.dumps(ld, ensure_ascii=False) + "</script>"
                '<a href="/jobs/SDE-125337/Operativer_Eink%C3%A4ufer___Produktionsplaner_(m_w_d)_/">Weitere interessante Jobs</a></body></html>')
        raw = "https://www.jobsuche-bw.de/jobs/16427091/Bäcker_und_Konditor_(m_w_d)_Bretten_Bäckerei_Tholle/"
        job = extract(html, raw, self.source, "Bäcker")
        self.assertEqual(job["company"], "Bäckerei Thollembeek GmbH & Co. KG")
        self.assertEqual(job["title"], "Bäcker & Konditor (m/w/d)")
        self.assertEqual(job["location"], "75015 Bretten Baden-Württemberg DE")
        self.assertEqual(job["posted"], "2026-10-30")
        self.assertIn("Quereinsteiger willkommen", job["description"])
        self.assertNotIn("&amp;", job["description"])
        # "Weitere interessante Jobs" on a detail page point to other ads.
        links, _ = discovery(html, raw, self.source, "Bäcker")
        self.assertIn("https://www.jobsuche-bw.de/jobs/SDE-125337/Operativer_Eink%C3%A4ufer___Produktionsplaner_(m_w_d)_", links)

    def test_observed_search_page_markup_for_elektro(self):
        slugs = {"SDE-122017": "Elektriker_(m_w_d)_Stuttgart_Firma_A", "SDE-132371": "Elektroniker_(m_w_d)_Ulm_Firma_B",
                 "16427672": "Elektroinstallateur_(m_w_d)_Bretten_Firma_C", "SDE-130415": "Servicetechniker_Elektro_Berlin_Firma_D",
                 "SDE-130418": "Elektroniker_fuer_Betriebstechnik_Hamburg_Firma_E"}
        teasers = "".join(
            f'<article><a data-testid="qa-hitzone" class="enhanced-link" href="/jobs/{i}/{s}/">Titel {i}</a></article>'
            for i, s in slugs.items())
        html = ("<html><body><h1>177 relevante Jobs</h1>" + teasers +
                '<a href="[www.google.de/test](https://www.google.de/test)">KI-Check</a>'
                '<a href="/jobs/SDE-122017/Elektriker_(m_w_d)_Stuttgart_Firma_A/?jobId=SDE-122017&si=abc&srp=0">Duplikat</a>'
                "</body></html>")
        base = "https://www.jobsuche-bw.de/suchergebnis/?fulltext=elektro&si=abc&jobId=SDE-122017&srp=0"
        links, following = discovery(html, base, self.source, "elektro")
        self.assertIsNone(following)
        expected = sorted(f"https://www.jobsuche-bw.de/jobs/{i}/{s}" for i, s in slugs.items())
        self.assertEqual(sorted(l for l in links if "?" not in l), expected)
        self.assertFalse([l for l in links if "google" in l])

    def test_listing_other_host_expired_initiative_and_irrelevant_are_dropped(self):
        self.assertIsNone(extract(page(), "https://www.jobsuche-bw.de/stellenangebote/pflege/", self.source, "Verkauf"))
        self.assertIsNone(extract(page(), OWN.replace("www.jobsuche-bw.de", "evil.test"), self.source, "Verkauf"))
        self.assertIsNone(extract(page(validThrough="2020-01-01"), OWN, self.source, "Verkauf"))
        self.assertIsNone(extract(page(title="Initiativbewerbung"), OWN, self.source, "Initiativ"))
        self.assertIsNone(extract(page(hiringOrganization={"@type": "Organization", "name": ""}), OWN, self.source, "Verkauf"))
        self.assertIsNone(extract(page(), OWN, self.source, "Buchhalter"))

    def test_aggregator_needs_explicit_approval_and_is_not_in_employers_group(self):
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers"}):
            self.assertNotIn("jobsuche_bw", approved_sources())
        with patch.dict(os.environ, {"SCRAPLING_APPROVED_SOURCES": "employers,jobsuche_bw"}):
            self.assertIn("jobsuche_bw", approved_sources())


if __name__ == "__main__":
    unittest.main()
