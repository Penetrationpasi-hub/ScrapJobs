"""Anzeigen über die Sitemap, die der Betreiber für Suchmaschinen veröffentlicht (z. B. Talention-Portale).

Sinnvoll, wenn die Stellenliste per JavaScript entsteht, die Anzeigenseiten selbst aber serverseitig ausgeliefert
werden. Gelesen wird nur die in der Konfiguration genannte Sitemap-Datei (eine <urlset>, keine Index-Dateien,
kein DOCTYPE). Jede Adresse muss dem Linkmuster der Quelle entsprechen; die Anzeige selbst wird wie überall auf
der Einzelseite geprüft (JSON-LD, Firma, Ablauf).
"""
import re
import xml.etree.ElementTree as ET

from extraction import extract, is_detail
from safe_http import FetchError


def locations(text):
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text, re.I):
        raise FetchError("unsupported", detail="Sitemap mit DOCTYPE/ENTITY abgelehnt")
    try:
        root = ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError:
        raise FetchError("unsupported", detail="Sitemap nicht lesbar") from None
    if not root.tag.endswith("}urlset") and root.tag != "urlset":
        raise FetchError("unsupported", detail="Keine urlset-Sitemap")
    found = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and node.text.strip():
            found.append(node.text.strip())
    return found


def sitemap(source, req, get, report):
    from employer_adapters import detail_document
    _, text = get(source.api, source, accept_xml=True)
    limit = getattr(req, "max_details", 10)
    links = []
    for raw in locations(text):
        if is_detail(raw, source) and raw not in links:
            links.append(raw)
    for raw in links[:limit]:
        document = detail_document(get, raw, source, report)
        if document is None:
            continue
        final, html = document
        job = extract(html, final, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
