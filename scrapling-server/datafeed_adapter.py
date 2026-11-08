"""Softgarden-Karriereseiten: der offizielle Stellen-Feed `/jobs.feed.json` (schema.org DataFeed).

Ein Abruf liefert alle Anzeigen mit Titel, Anzeigenadresse, Datum, Arbeitgeber und Ort. Beschreibungen werden nicht
übernommen. Platzhalterwerte ("-") in der Adresse werden entfernt. Jede Anzeige läuft durch dieselbe Prüfung wie ein
JobPosting (Host, Linkmuster, Titel, Arbeitgeber, Initiativbewerbungen, Ablauf).
"""
from safe_http import FetchError


def items(data):
    if not isinstance(data, dict) or not isinstance(data.get("dataFeedElement"), list):
        raise FetchError("unsupported", detail="Kein schema.org-DataFeed")
    for entry in data["dataFeedElement"]:
        row = entry.get("item") if isinstance(entry, dict) else None
        if isinstance(row, dict) and row.get("@type") == "JobPosting":
            yield row


def clean(row):
    row = dict(row)
    place = row.get("jobLocation")
    if isinstance(place, dict) and isinstance(place.get("address"), dict):
        address = {k: v for k, v in place["address"].items() if not (isinstance(v, str) and v.strip() in ("", "-"))}
        row["jobLocation"] = {**place, "address": address}
    row.pop("description", None)  # wird nicht veröffentlicht
    return row


def datafeed(source, req, get, report):
    from employer_adapters import from_record, json_document
    data = json_document(get, source.api, source)
    for row in items(data):
        url = row.get("url")
        if not isinstance(url, str):
            report["filtered"] += 1
            continue
        job = from_record(clean(row), url, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
