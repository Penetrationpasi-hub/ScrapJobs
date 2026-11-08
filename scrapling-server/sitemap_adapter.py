"""Anzeigen über die Sitemap, die der Betreiber für Suchmaschinen veröffentlicht (z. B. Talention-Portale).

Sinnvoll, wenn die Stellenliste per JavaScript entsteht, die Anzeigenseiten selbst aber serverseitig ausgeliefert
werden. Gelesen wird die in der Konfiguration genannte Sitemap-Datei; ist sie ein Index (<sitemapindex>), werden
höchstens MAX_PARTS Untersitemaps desselben Hosts eine Ebene tief gelesen (kein DOCTYPE, keine tieferen Indizes). Jede Adresse muss dem Linkmuster der Quelle entsprechen; die Anzeige selbst wird wie überall auf
der Einzelseite geprüft (JSON-LD, Firma, Ablauf).
"""
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from extraction import extract, is_detail
from safe_http import FetchError


MAX_PARTS = 6


def parse(text):
    """Liefert ("urlset" | "index", Adressen)."""
    if re.search(r"<!(?:DOCTYPE|ENTITY)", text, re.I):
        raise FetchError("unsupported", detail="Sitemap mit DOCTYPE/ENTITY abgelehnt")
    try:
        root = ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError:
        raise FetchError("unsupported", detail="Sitemap nicht lesbar") from None
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in ("urlset", "sitemapindex"):
        raise FetchError("unsupported", detail="Keine urlset-Sitemap")
    found = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and node.text.strip():
            found.append(node.text.strip())
    return ("index" if kind == "sitemapindex" else "urlset"), found


def locations(text):
    kind, found = parse(text)
    if kind != "urlset":
        raise FetchError("unsupported", detail="Keine urlset-Sitemap")
    return found


def sitemap(source, req, get, report):
    from employer_adapters import detail_document
    _, text = get(source.api, source, accept_xml=True)
    limit = getattr(req, "max_details", 10)
    kind, found = parse(text)
    if kind == "index":
        host = urlsplit(source.api).hostname
        parts = [u for u in found if urlsplit(u).scheme == "https" and urlsplit(u).hostname == host][:MAX_PARTS]
        found = []
        for part in parts:
            _, sub = get(part, source, accept_xml=True)
            sub_kind, urls = parse(sub)
            if sub_kind == "urlset":
                found.extend(urls)
    links = []
    for raw in found:
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
