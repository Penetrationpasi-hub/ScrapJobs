import unittest

from extraction import extract
from sources import registry

URL = "https://www.frech.com/de/ausbildungsstelle-details/elektroniker-fuer-betriebstechnik-m-w-d.html"
PAGE = """<html><head><title>Ausbildung zum Elektroniker/ -in für Betriebstechnik (m/w/d) bei Frech - Oskar Frech GmbH + Co. KG</title></head><body>
<div class="mod_breadcrumb block"><div class="mod_breadcrumb_inside">
<div class="pagetitle">Ausbildung zum Elektroniker/ -in für Betriebstechnik (m/w/d) bei Frech</div></div></div>
<div class="mod_newsreader block"><p>Als Elektroniker sind Sie für die Montage zuständig.</p></div>
<footer><div class="autogrid one_fourth footer-col1 block"><div class="ce_text first last block"><h4>Oskar Frech GmbH + Co. KG</h4>
<p>Schorndorfer Straße 32<br>73614 Schorndorf</p><p>+49 (0) 7181 - 70 20</p></div></div></footer></body></html>"""


class FrechTest(unittest.TestCase):
    def test_contao_page_is_read_from_title_and_footer(self):
        job = extract(PAGE, URL, registry()["frech"])
        self.assertEqual(job["title"], "Ausbildung zum Elektroniker/ -in für Betriebstechnik (m/w/d) bei Frech")
        self.assertEqual(job["company"], "Oskar Frech GmbH + Co. KG")
        self.assertEqual(job["location"], "Schorndorfer Straße 32 73614 Schorndorf")

    def test_foreign_footer_is_rejected(self):
        self.assertIsNone(extract(PAGE.replace("Oskar Frech GmbH + Co. KG</h4>", "Fremd GmbH</h4>"), URL, registry()["frech"]))


class FrechLinksTest(unittest.TestCase):
    def test_relative_links_use_the_base_href(self):
        from extraction import discovery
        html = ('<html><head><base href="https://www.frech.com/"></head><body>'
                '<a href="de/job-details-de/it-projektmanager-m-w-d.html">IT</a>'
                '<a href="de/ausbildungsstelle-details/elektroniker-fuer-betriebstechnik-m-w-d.html">Azubi</a></body></html>')
        links, _ = discovery(html, "https://www.frech.com/de/jobboerse.html", registry()["frech"])
        self.assertEqual(sorted(links), [
            "https://www.frech.com/de/ausbildungsstelle-details/elektroniker-fuer-betriebstechnik-m-w-d.html",
            "https://www.frech.com/de/job-details-de/it-projektmanager-m-w-d.html"])
