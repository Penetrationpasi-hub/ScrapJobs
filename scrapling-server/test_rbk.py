import unittest

from extraction import extract
from sources import registry

URL = ("https://jobs.smartrecruiters.com/RobertBoschKrankenhausGmbH/"
       "744000160143081-medizinischer-fachangestellter-mta-f-oder-mtra-m-w-d-fur-das-kardio-mrt-fur-den-spatdienst-14-00-22-00-uhr-")
PAGE = """<html><head><title>Robert Bosch Krankenhaus GmbH Medizinischer Fachangestellter | SmartRecruiters</title>
<meta property="og:title" content="Medizinischer Fachangestellter, MTA-F oder MTRA (m/w/d) für das Kardio-MRT"></head><body>
<main class="jobad-main job" itemscope itemtype="http://schema.org/JobPosting">
<h1 itemprop="title">Medizinischer Fachangestellter, MTA-F oder MTRA (m/w/d) für das Kardio-MRT</h1>
<ul><li itemprop="jobLocation" itemscope itemtype="http://schema.org/Place"><span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
<meta itemprop="addressCountry" content="Germany"><meta itemprop="addressLocality" content="Stuttgart">
<meta itemprop="addressRegion" content="Baden-Württemberg"><meta itemprop="postalCode" content="70376">
<meta itemprop="streetAddress" content="Auerbachstraße 110"></span></li></ul>
<div itemprop="hiringOrganization" itemscope itemtype="http://schema.org/Organization">
<meta itemprop="name" content="Robert Bosch Krankenhaus GmbH"><meta itemprop="logo" content="https://example.test/logo.png"></div>
<meta itemprop="datePosted" content="2026-11-06T08:53:04.308Z">
<div itemprop="description"><p>Stellenbeschreibung Kardio-MRT</p></div></main></body></html>"""


class RobertBoschKrankenhausTest(unittest.TestCase):
    def test_smartrecruiters_microdata_with_meta_organization(self):
        job = extract(PAGE, URL, registry()["robert_bosch_krankenhaus"])
        self.assertEqual(job["company"], "Robert Bosch Krankenhaus GmbH")
        self.assertEqual(job["posted"], "2026-11-06")
        self.assertIn("Stuttgart", job["location"])
        self.assertEqual(job["title"], "Medizinischer Fachangestellter, MTA-F oder MTRA (m/w/d) für das Kardio-MRT")
