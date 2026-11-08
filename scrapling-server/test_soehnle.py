import unittest

from extraction import extract
from sources import registry

URL = "https://www.soehnle-professional.com/de/karriere/62/applikationstechniker-systemlosungen-mwd"
PAGE = """<html><head><title>Applikationstechniker Systemlösungen (m/w/d) - Soehnle Industrial Solutions</title>
<meta property="og:title" content="Applikationstechniker Systemlösungen (m/w/d)" /></head><body>
<div class="special-content"><h1>Applikationstechniker Systeml&ouml;sungen (m/w/d)</h1>
<p>Gestalten Sie unseren dynamischen Wachstumskurs mit als Applikationstechniker.</p></div>
<div class="row copyright"><div><span>&copy; 2026 Soehnle Industrial Solutions GmbH</span></div></div></body></html>"""


class SoehnleTest(unittest.TestCase):
    def test_page_without_structured_data_is_read_from_title_and_footer(self):
        job = extract(PAGE, URL, registry()["soehnle"])
        self.assertEqual(job["title"], "Applikationstechniker Systemlösungen (m/w/d)")
        self.assertEqual(job["company"], "Soehnle Industrial Solutions GmbH")
        self.assertEqual(job["location"], "")

    def test_other_company_footer_is_rejected(self):
        self.assertIsNone(extract(PAGE.replace("Soehnle Industrial Solutions GmbH", "Fremd GmbH"), URL, registry()["soehnle"]))
