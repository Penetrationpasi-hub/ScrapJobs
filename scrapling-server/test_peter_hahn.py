import json
import unittest

from extraction import discovery, extract
from sources import registry

AD = "https://jobs.peterhahn.com/stellenangebote/Minijob-Passformmodel-m-w-d-Anprobe-Konfektionsgroesse-36-Winterbach-PETER-HAHN-GmbH--653128593"


class PeterHahnTest(unittest.TestCase):
    def test_list_page_on_com_host_finds_the_ad_but_not_the_application_form(self):
        html = f'<a href="{AD}">Minijob</a><a href="{AD}/bewerbung">Bewerben</a><a href="https://jobs.peterhahn.com/stellenangebote/173390358/bewerbung">x</a>'
        links, _ = discovery(html, "https://jobs.peterhahn.com/jobs", registry()["peter_hahn"])
        self.assertEqual(links, [AD])

    def test_search_start_is_the_com_portal(self):
        self.assertEqual(registry()["peter_hahn"].search, "https://jobs.peterhahn.com/jobs")

    def test_ad_with_jsonld_is_read(self):
        posting = {"@context": "https://schema.org/", "@type": "JobPosting", "datePosted": "2026-11-08T07:40:57.000",
                   "title": "Minijob – Passformmodel (m/w/d)", "hiringOrganization": {"@type": "Organization", "name": "Peter Hahn GmbH"},
                   "jobLocation": {"@type": "Place", "address": {"addressLocality": "Winterbach", "postalCode": "73650", "addressCountry": "DE"}},
                   "description": "<p>Standort</p><p>Winterbach</p>"}
        html = '<script type="application/ld+json">' + json.dumps(posting) + "</script>"
        job = extract(html, AD, registry()["peter_hahn"])
        self.assertEqual((job["company"], job["posted"]), ("Peter Hahn GmbH", "2026-11-08"))
