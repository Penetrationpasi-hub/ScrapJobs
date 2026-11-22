"""GPM Personalservice und Liebert GmbH: Anzeigenliste über die öffentliche Persy-Jobbörsen-Schnittstelle.

Die Stellenseiten der GPM (www.gpm-personalservice.de/jobs-in-stuttgart) und der Liebert GmbH
(www.liebertgmbh.de/stellenangebote/) enthalten nur ein JavaScript-Widget
(`jobExchange: '<Token>'` von statics.germanpersonnel.de), im HTML steht keine Anzeige. Das Widget
liest per GET dieselbe öffentliche Schnittstelle, die hier gelesen wird:
`https://www.germanpersonnel.de/persy/api/v1/channel_posting/jobexchange/<Token>/?options=…&filters={}&fields=[…]`
(höchstens 100 Anzeigen je Abruf). Jede Anzeige liefert Titel, Arbeitgeber, Standort mit PLZ, Datum und die
öffentliche Adresse (`DetailsURL` auf www.persy.jobs). Daraus wird ein JobPosting-Datensatz gebaut und wie überall
geprüft (Host, Adressmuster, Titel, Arbeitgeber, Relevanz). Die Einzelseiten auf persy.jobs werden nicht abgerufen.
Der Leser ist an die bekannten Quellen (`gpm`, `liebert`: je ein fester Token, diese Felder) gebunden.
"""
import json
import re
from urllib.parse import quote, urlsplit

import geo
from employer_adapters import json_document
from extraction import extract
from safe_http import FetchError

from sources import PERSY_EXCHANGES, persy_base

BASE = persy_base("gpm")  # Rückwärtskompatibel: die GPM-Schnittstelle
PAGE = 100  # die Schnittstelle erlaubt höchstens 100
MAX_PAGES = 5
FIELDS = ["Posting.Title", "Posting.Locations.ZipCode", "Posting.Locations.CityName",
          "Posting.Locations.Country.CountryName", "Posting.OrganisationUnit.Name", "PublishingDate"]
DETAIL_HOST = "www.persy.jobs"
DETAIL_PATH = re.compile(r"^/persy/l/job-[a-z0-9]{3,12}-a-stellenangebote-[A-Za-z0-9-]{3,200}$")


def page_url(offset, key="gpm"):
    options = json.dumps({"limit": [{"eq": PAGE}], "offset": [{"eq": offset}]}, separators=(",", ":"))
    fields = json.dumps(FIELDS, separators=(",", ":"))
    return f"{persy_base(key)}?options={quote(options, safe='')}&filters={{}}&fields={quote(fields, safe='')}"


def missing_robots_scope(raw, source, options):
    """The Persy API host publishes no robots.txt (404). Only the list pages of the known sources are covered by that."""
    if source.key not in PERSY_EXCHANGES or source.adapter != "persy_exchange" or options != {"accept_json": True}:
        return False
    return raw in {page_url(offset, source.key) for offset in range(0, PAGE * MAX_PAGES, PAGE)}


def record(row):
    """JobPosting-artiger Datensatz aus einem Listeneintrag, nur mit belegten Feldern."""
    if not isinstance(row, dict) or not isinstance(row.get("DetailsURL"), str):
        return None
    link = urlsplit(row["DetailsURL"])
    if (link.scheme != "https" or link.hostname != DETAIL_HOST or link.username or link.password or link.port
            or link.query or link.fragment or not DETAIL_PATH.fullmatch(link.path)):
        return None
    posting = row.get("Posting") if isinstance(row.get("Posting"), dict) else {}
    unit = posting.get("OrganisationUnit") if isinstance(posting.get("OrganisationUnit"), dict) else {}
    places = []
    for loc in posting.get("Locations") or []:
        if not isinstance(loc, dict):
            continue
        country = loc.get("Country") if isinstance(loc.get("Country"), dict) else {}
        address = {"@type": "PostalAddress", "addressLocality": loc.get("CityName") or "",
                   "postalCode": loc.get("ZipCode") or "", "addressCountry": country.get("CountryName") or ""}
        if address["addressLocality"] or address["postalCode"]:
            places.append({"@type": "Place", "address": address})
    data = {"@type": "JobPosting", "title": posting.get("Title"), "hiringOrganization": {"name": unit.get("Name")},
            "url": row["DetailsURL"], "jobLocation": places, "datePosted": str(row.get("PublishingDate") or "")[:10]}
    return data


def distance(origin, data):
    if not origin:
        return None
    found = [geo.distance_km(origin, " ".join(part for part in (p["address"]["postalCode"], p["address"]["addressLocality"]) if part))
             for p in data["jobLocation"]]
    found = [value for value in found if value is not None]
    return min(found) if found else None


def persy(source, req, get, report):
    rows = []
    pages = getattr(req, "max_pages", MAX_PAGES)
    for offset in range(0, PAGE * pages, PAGE):
        page = json_document(get, page_url(offset, source.key), source)
        if not isinstance(page, list):
            raise FetchError("unsupported", detail="Persy-Antwort ist keine Liste")
        rows.extend(page)
        if len(page) < PAGE:
            break
    else:
        report["detail"] = f"mehr als {PAGE * pages} Anzeigen, nur die ersten gelesen"
    origin = geo.center(req.location) if getattr(req, "location", "") else None
    radius = getattr(req, "radius_km", 25)
    ranked = []
    for row in rows:
        data = record(row)
        if not data:
            report["filtered"] += 1
            continue
        near = distance(origin, data)
        if near is not None and near > radius:
            continue
        ranked.append((near is None, near or 0, data))
    ranked.sort(key=lambda item: (item[0], item[1]))  # known distance first, nearest first
    for _, _, data in ranked:
        safe = json.dumps(data).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + safe + "</script>", data["url"], source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
