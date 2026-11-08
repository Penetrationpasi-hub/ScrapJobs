import unittest
from datetime import datetime, timezone

from extraction import extract, microdata, stamp
from scrapling import Selector
from sources import registry

URL = "https://careers.mahle.com/job/Markgr%C3%B6ningen-Ausbildung-Industriemechaniker-%28mwd%29-2027-71706/1405005433"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def page(title="Ausbildung: Industriemechaniker (m/w/d) 2027", company="MAHLE", valid="Fri Apr 30 22:00:00 UTC 2027",
         extra="", head="", location_meta='<meta itemprop="streetAddress" content="Markgröningen, DE, 71706">'):
    return f'''<!DOCTYPE html><html><head><title>{title} Stellendetails | MAHLE</title>{head}</head><body>
<div class="jobDisplayShell" itemscope="itemscope" itemtype="http://schema.org/JobPosting"><span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place"><span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">{location_meta}</span></span><meta itemprop="datePosted" content="Sun Nov 08 02:00:00 UTC 2026"><meta itemprop="validThrough" content="{valid}"><meta itemprop="hiringOrganization" content="{company}">
<div class="job"><h1><span xml:lang="de-DE" lang="de-DE" itemprop="title" data-careersite-propertyid="title">{title}
</span></h1>
<span itemprop="description" data-careersite-propertyid="description"><span class="jobdescription"><p><strong>Das erwartet dich bei uns:</strong></p><ul><li>Fundierte 3,5 jährige Ausbildung</li></ul></span></span>
<span data-careersite-propertyid="location"><p id="job-location"><span class="jobGeoLocation">Markgröningen, DE, 71706</span></p></span>
</div></div>{extra}</body></html>'''


class MicrodataTest(unittest.TestCase):
    source = registry()["mahle"]

    def test_reads_successfactors_job_page(self):
        job = extract(page(), URL, self.source, "", now=NOW)
        self.assertEqual(job["title"], "Ausbildung: Industriemechaniker (m/w/d) 2027")
        self.assertEqual(job["company"], "MAHLE")
        self.assertEqual(job["location"], "Markgröningen, DE, 71706")
        self.assertEqual(job["posted"], "2026-11-08")
        self.assertEqual(job["url"], URL)

    def test_expired_posting_is_dropped(self):
        self.assertIsNone(extract(page(valid="Fri Apr 30 22:00:00 UTC 2026"), URL, self.source, "", now=NOW))

    def test_unparseable_expiry_is_dropped_not_guessed(self):
        self.assertIsNone(extract(page(valid="bald"), URL, self.source, "", now=NOW))

    def test_unsolicited_application_is_dropped(self):
        self.assertIsNone(extract(page(title="Initiativbewerbung Remshalden (m/w/d)"), URL, self.source, "", now=NOW))

    def test_missing_employer_is_dropped(self):
        self.assertIsNone(extract(page(company=""), URL, self.source, "", now=NOW))

    def test_two_postings_on_one_page_are_not_one_vacancy(self):
        second = '<div itemscope itemtype="http://schema.org/JobPosting"><span itemprop="title">Zweite Rolle</span></div>'
        self.assertIsNone(extract(page(extra=second), URL, self.source, "", now=NOW))

    def test_json_ld_still_has_priority(self):
        ld = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Aus JSON-LD",'
              '"hiringOrganization":{"name":"MAHLE GmbH"}}</script>')
        job = extract(page(head=ld), URL, self.source, "", now=NOW)
        self.assertEqual((job["title"], job["company"]), ("Aus JSON-LD", "MAHLE GmbH"))

    def test_other_hosts_are_still_rejected(self):
        self.assertIsNone(extract(page(), "https://evil.example/job/x/1", self.source, "", now=NOW))

    def test_location_falls_back_to_visible_text(self):
        job = extract(page(location_meta=""), URL, self.source, "", now=NOW)
        self.assertEqual(job["location"], "Markgröningen, DE, 71706")

    def test_search_term_is_matched_against_title_and_description(self):
        self.assertIsNotNone(extract(page(), URL, self.source, "Industriemechaniker", now=NOW))
        self.assertIsNone(extract(page(), URL, self.source, "Buchhalter", now=NOW))

    def test_stamp_formats(self):
        self.assertEqual(stamp("Sun Nov 08 02:00:00 UTC 2026").date().isoformat(), "2026-11-08")
        self.assertEqual(stamp("2026-11-08T02:00:00Z").date().isoformat(), "2026-11-08")
        self.assertIsNone(stamp("nie"))

    def test_page_without_microdata_is_not_claimed(self):
        self.assertIsNone(microdata(Selector("<html><body><h1>Nichts</h1></body></html>")))


if __name__ == "__main__":
    unittest.main()
