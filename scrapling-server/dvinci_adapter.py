"""d.vinci-Karriereportale (z. B. WIRmachenDRUCK): die Stellenliste steckt als JSON im Seitenquelltext.

Gelesen wird ausschließlich die öffentliche Listenseite (`var DvinciData = {...}`), kein JavaScript,
keine Bewerbungs-API. Jede Stelle läuft durch dieselbe Prüfung wie ein JobPosting-Datensatz
(Host, Detail-Muster, Titel, Arbeitgeber, Ablaufdatum). Infoseiten wie die Initiativbewerbung
(`/de/jobs/4/intro`) stehen nicht in der Liste und werden deshalb nie ausgegeben.
"""
import json
import re

from extraction import extract, plain
from safe_http import FetchError

MARKER = re.compile(r"var\s+DvinciData\s*=\s*")


def publications(html):
    match = MARKER.search(html)
    if not match:
        raise FetchError("unsupported", detail="DvinciData nicht gefunden")
    try:
        data, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError:
        raise FetchError("unsupported", detail="DvinciData nicht lesbar") from None
    rows = data.get("jobPublications") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise FetchError("unsupported", detail="DvinciData ohne jobPublications")
    return rows


def record(row):
    """JobPosting-artiger Datensatz aus einem Listeneintrag, nur mit belegten Feldern."""
    if not isinstance(row, dict) or not isinstance(row.get("jobPublicationURL"), str):
        return None
    opening = row.get("jobOpening") if isinstance(row.get("jobOpening"), dict) else {}
    company = opening.get("company") if isinstance(opening.get("company"), dict) else {}
    place = plain(opening.get("location")) if isinstance(opening.get("location"), str) else ""
    if not place:
        names = [plain(loc.get("name")) for loc in opening.get("locations") or [] if isinstance(loc, dict)]
        place = ", ".join(name for name in names if name)
    data = {"@type": "JobPosting", "title": row.get("position") or row.get("pageTitle"),
            "hiringOrganization": {"name": company.get("name")}, "url": row["jobPublicationURL"],
            "jobLocation": {"address": {"addressLocality": place}} if place else [],
            "datePosted": opening.get("createdDate") or ""}
    if row.get("endDate"):
        data["validThrough"] = row["endDate"]
    return data


def dvinci(source, req, get, report):
    final, html = get(source.search, source)
    for row in publications(html):
        data = record(row)
        if not data:
            report["filtered"] += 1
            continue
        safe = json.dumps(data).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + safe + "</script>", data["url"], source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
