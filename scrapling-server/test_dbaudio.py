"""d&b audiotechnik: Anzeigen ohne JobPosting-JSON-LD, Felder aus og:title, <title> und Karriere-Kopfzeile."""
import re
import unittest

from extraction import extract, is_detail
from sources import registry

BASE = "https://www.dbaudio.com/global/de/ueber-db/karriere/jobs/"


def detail_page(title, place, extra_head=""):
    og = f'<meta property="og:title" content="{title}">' if title else ""
    return (f'<html><head><title>{title or "Seite"} | d&amp;b audiotechnik</title>{og}{extra_head}</head><body>'
            f'<section class="b_textmedia__container"><h2 class="b_headline"> {title} </h2>'
            f'<p>Starte dein Leben bei uns. Du analysierst Risiken, entwickelst pragmatische Loesungen und arbeitest eng mit allen Fachbereichen zusammen.</p></section>'
            f'<ul class="b_careerMeta__list">'
            f'<li class="b_careerMeta__item"><span class="b_careerMeta__label"> Abteilung: </span><span class="b_careerMeta__value"></span></li>'
            f'<li class="b_careerMeta__item"><span class="b_careerMeta__label"> Ort: </span><span class="b_careerMeta__value"> {place} </span></li>'
            f'<li class="b_careerMeta__item"><span class="b_careerMeta__label"> Art: </span><span class="b_careerMeta__value"> Direkteinstieg </span></li>'
            f'</ul></body></html>')


class DbAudioTest(unittest.TestCase):
    source = registry()["db_audiotechnik"]

    def test_list_links_match_and_foreign_links_do_not(self):
        good = BASE + "it-security-specialist-wmd-req-2026-00000180/"
        self.assertTrue(is_detail(good, self.source))
        self.assertFalse(is_detail(BASE, self.source))
        self.assertFalse(is_detail("https://www.dbaudio.com/global/de/ueber-db/karriere/dein-weg/", self.source))

    def test_detail_without_json_ld_is_read_from_selectors(self):
        url = BASE + "it-security-specialist-wmd-req-2026-00000180/"
        job = extract(detail_page("IT Security Specialist (w/m/d)", "Deutschland, Backnang"), url, self.source, "")
        self.assertEqual((job["title"], job["company"], job["location"]),
                         ("IT Security Specialist (w/m/d)", "d&b audiotechnik", "Deutschland, Backnang"))
        self.assertEqual(job["url"], url.rstrip("/"))

    def test_page_without_title_is_rejected(self):
        why = []
        url = BASE + "ohne-titel-req-2026-00000001/"
        self.assertIsNone(extract(detail_page("", "Backnang"), url, self.source, "", why=why))
        self.assertTrue(why)

    def test_foreign_company_is_rejected(self):
        html = detail_page("Servicetechniker (m/w/d)", "Backnang").replace("d&amp;b audiotechnik", "Andere GmbH")
        self.assertIsNone(extract(html, BASE + "x-req-2026-00000002/", self.source, ""))


if __name__ == "__main__":
    unittest.main()
