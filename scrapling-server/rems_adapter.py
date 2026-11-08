"""REMS-Karriereportal: die Stellenliste steht vollständig im HTML der Übersichtsseite.

Gelesen wird nur `recruitment.rems.de/stellenangebote` (Abschnitte DEU/AUT/CHE). Die Einzelseiten haben keine
strukturierten Daten und werden nicht abgerufen. Der Arbeitgeber gilt nur als belegt, wenn der Seitentitel
"REMS Recruitment-Portal" lautet; jede Stelle läuft durch die übliche Prüfung (Host, Linkmuster, Titel, Datum).
"""
import json
import re
from urllib.parse import urljoin

from scrapling import Selector

from extraction import extract, plain
from safe_http import FetchError

COUNTRIES = ("DEU", "AUT", "CHE")
PRELINE = re.compile(r"^\s*([A-Z]{3})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})\s*$")


def listing(html, base):
    if not re.search(r"<title>\s*REMS\s+Recruitment-Portal\s*</title>", html, re.I):
        raise FetchError("unsupported", detail="Seitentitel nicht 'REMS Recruitment-Portal'")
    page = Selector(html)
    rows = []
    for code in COUNTRIES:
        for entry in page.css(f"div#{code} div.jobentry"):
            link = entry.css("h2 a")
            if len(link) != 1:
                rows.append(None)
                continue
            place = plain(" ".join(entry.css("h3").getall()))
            place = re.sub(r"^\s*Standort\s+", "", place)
            stamp = PRELINE.match(plain(" ".join(entry.css(".jobentrypreline").getall())))
            posted = f"{stamp.group(4)}-{stamp.group(3)}-{stamp.group(2)}" if stamp and stamp.group(1) == code else ""
            rows.append({"title": plain(link[0].get()), "url": urljoin(base, link[0].attrib.get("href", "")),
                         "place": place + ("" if code == "DEU" or not place else f", {code}"), "posted": posted})
    return rows


def rems_list(source, req, get, report):
    final, html = get(source.search, source)
    for row in listing(html, final):
        if not row or not row["title"]:
            report["filtered"] += 1
            continue
        data = {"@type": "JobPosting", "title": row["title"], "hiringOrganization": {"name": "REMS"},
                "url": row["url"], "datePosted": row["posted"],
                "jobLocation": {"address": {"addressLocality": row["place"]}} if row["place"] else []}
        safe = json.dumps(data).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + safe + "</script>", row["url"], source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
