"""Personio-Karriereseiten: der öffentliche Stellenfeed `https://<mandant>.jobs.personio.de/xml`.

Gelesen werden nur Titel, Firma (subcompany), Standort, Datum und ID, die Beschreibungen werden verworfen.
Die Anzeigen-URL ist die öffentliche Seite `https://<mandant>.jobs.personio.de/job/<id>`. Jede Stelle läuft
durch dieselbe Prüfung wie ein JobPosting (Host, Linkmuster, Titel, Arbeitgeber, Initiativbewerbungen).
"""
import json
import re
import xml.etree.ElementTree as ET

from extraction import extract, plain
from safe_http import FetchError

# Ein einzelnes "&" im Text (z. B. "GmbH & Co. KG") ist kein gültiges XML und wird maskiert.
BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)")


def positions(text):
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text, re.I):
        raise FetchError("unsupported", detail="Feed mit DOCTYPE/ENTITY abgelehnt")
    try:
        root = ET.fromstring(BARE_AMPERSAND.sub("&amp;", text.lstrip("﻿")))
    except ET.ParseError:
        raise FetchError("unsupported", detail="Personio-Feed nicht lesbar") from None
    if root.tag != "workzag-jobs":
        raise FetchError("unsupported", detail="Kein Personio-Feed")
    rows = []
    for node in root.findall("position"):
        def field(name):
            child = node.find(name)
            return plain(child.text) if child is not None and child.text else ""
        offices = [field("office")] + [plain(o.text or "") for o in node.findall("additionalOffices/office")]
        places = []
        for place in offices:
            if place and place not in places:
                places.append(place)
        rows.append({"id": field("id"), "title": field("name"), "company": field("subcompany"),
                     "place": ", ".join(places[:5]), "posted": field("createdAt")})
    return rows


def personio(source, req, get, report):
    _, text = get(source.api, source, accept_xml=True)
    host = source.hosts[0]
    for row in positions(text):
        if not re.fullmatch(r"\d{1,12}", row["id"]):
            report["filtered"] += 1
            continue
        url = f"https://{host}/job/{row['id']}"
        data = {"@type": "JobPosting", "title": row["title"], "hiringOrganization": {"name": row["company"]},
                "url": url, "datePosted": row["posted"],
                "jobLocation": {"address": {"addressLocality": row["place"]}} if row["place"] else []}
        safe = json.dumps(data).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + safe + "</script>", url, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
