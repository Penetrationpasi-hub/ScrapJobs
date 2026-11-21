"""Stadt Waiblingen: Stellenliste von karriere.waiblingen.de/offene-stellen.

Das Karriereportal ist eine Baukasten-Seite (one.com): alle Stellen stehen als Textblöcke direkt auf der rund
3 MB großen Listenseite, es gibt keine Einzelseiten mit Stellendaten (der Link „Bewirb Dich jetzt!“ führt zu einem
Bewerbungsfragebogen). Gelesen wird deshalb nur diese eine Seite (erhöhtes Limit über `large_page`, sonst 2 MB). Die Textblöcke
stehen im Rohquelltext nicht als HTML, sondern als JSON-Zustand in einem <script> (Atome: header, plain-text, menu-v2,
list, link-group); der Leser liest diesen Zustand und fällt auf das gerenderte DOM zurück.
Pro Block mit Bewerbungslink entsteht ein JobPosting-Datensatz: Titel (erste Überschrift), Kurztext, Frist
(„bis zum TT.MM.JJJJ“ als validThrough) und der Bewerbungslink als Anzeigenadresse. Arbeitgeber und Ort sind fest
„Stadt Waiblingen“, weil die Seite nur Stellen der Stadtverwaltung führt. Die Prüfung läuft wie überall über
`extract` (Host, Adressmuster, Titel, Relevanz, Ablaufdatum).
"""
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from scrapling import Selector

from extraction import extract, plain
from safe_http import FetchError

HOST = "karriere.waiblingen.de"
LIST_URL = "https://karriere.waiblingen.de/offene-stellen"
LINK = re.compile(r"^https://karriere\.waiblingen\.de/[a-z0-9-]{3,80}$")
APPLY_TEXT = re.compile(r"bewirb|bewerben sie|erfahre mehr|zur bewerbung", re.I)
DEADLINE = re.compile(r"bis\s+(?:zum\s+)?(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)


def flat(text):
    return re.sub(r"\s+", " ", plain(text)).strip()


def blocks_text(node):
    """Alle Textblöcke (Draft.js `blocks`) unterhalb eines JSON-Knotens in Reihenfolge."""
    out = []
    if isinstance(node, dict):
        if isinstance(node.get("blocks"), list):
            out.extend(flat(b.get("text") or "") for b in node["blocks"] if isinstance(b, dict))
        for key, value in node.items():
            if key not in {"blocks", "styles"}:
                out.extend(blocks_text(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(blocks_text(value))
    return [t for t in out if t]


def menu_text(atom):
    """Eckdaten-Zeilen („Umfang: 100 %“) aus einem menu-v2-Atom."""
    rows = []
    for item in (atom.get("data") or {}).get("items") or []:
        data = item.get("data") if isinstance(item, dict) else None
        if isinstance(data, dict) and (data.get("link_text") or data.get("link_subtitle")):
            rows.append(flat(f"{data.get('link_text') or ''} {data.get('link_subtitle') or ''}"))
    return rows


def state_molecules(html):
    """Die Seite trägt ihren Inhalt als JSON-Zustand in einem <script> (rund 1 MB); er ist unabhängig vom Rendern."""
    for raw in re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S | re.I):
        if '"first_link_href"' not in raw or not raw.lstrip().startswith("{"):
            continue
        try:
            state = json.loads(raw)
        except ValueError:
            continue
        stack = [state]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if isinstance(node.get("atoms"), list):
                    yield node
                stack.extend(reversed(list(node.values())))
            elif isinstance(node, list):
                stack.extend(reversed(node))


def postings_from_state(html):
    seen = set()
    for molecule in state_molecules(html):
        atoms = [a for a in molecule["atoms"] if isinstance(a, dict)]
        links = [(a.get("data") or {}).get("first_link_href") for a in atoms if a.get("type") == "link-group"]
        links = [l for l in links if isinstance(l, str) and re.fullmatch(r"/[a-z0-9-]{3,80}", l)]
        header = next((a for a in atoms if a.get("type") == "header"), None)
        # Eine Stelle hat die Eckdatenzeile „Umfang: …“ (menu-v2-Atom); Einleitungs-Teaser mit Adresse nicht.
        if len(links) != 1 or not header or links[0] == "/offene-stellen" or not any(row.startswith("Umfang") for a in atoms if a.get("type") == "menu-v2" for row in menu_text(a)):
            continue
        title = " ".join(blocks_text(header))
        url = "https://" + HOST + links[0]
        parts = []
        for atom in atoms:
            if atom.get("type") in {"header", "link-group", "contacts", "image", "line"}:
                continue
            parts.extend(menu_text(atom) if atom.get("type") == "menu-v2" else blocks_text(atom))
        body = " ".join(parts)
        if not title or url in seen or len(body) < 60:
            continue
        seen.add(url)
        yield url, title, body


def postings(html):
    rows = list(postings_from_state(html))
    if rows:
        for url, title, body in rows:
            yield url, title, body, deadline(body)
        return
    yield from postings_from_dom(html)


def deadline(body):
    until = DEADLINE.search(body)
    if not until:
        return ""
    try:
        return datetime(int(until[3]), int(until[2]), int(until[1]), 23, 59, 59).strftime("%Y-%m-%dT%H:%M:%S+01:00")
    except ValueError:
        return ""


def postings_from_dom(html):
    page = Selector(re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S | re.I))
    seen = set()
    for block in page.css("div.con-kit-molecule-textBlock"):
        links = [a for a in block.css("a[href]") if LINK.fullmatch(a.attrib.get("href", ""))
                 and APPLY_TEXT.search(flat(a.get_all_text()))]
        if len(links) != 1:
            continue
        url = links[0].attrib["href"]
        heading = block.css("[data-atom=header]")
        title = flat(heading[0].get_all_text()) if heading else ""
        text = flat(block.get_all_text())
        if not title or url in seen or len(text) < 120:
            continue
        seen.add(url)
        body = text[len(title):].strip() if text.startswith(title) else text
        yield url, title, body, deadline(body)


def waiblingen(source, req, get, report):
    final, html = get(LIST_URL, source, large_page=True)
    if urlsplit(final).hostname != HOST:
        raise FetchError("unsupported", detail="Weiterleitung auf " + final)
    found = 0
    for url, title, body, valid in postings(html):
        found += 1
        data = {"@type": "JobPosting", "title": title, "description": body[:4000], "url": url,
                "hiringOrganization": {"name": "Stadt Waiblingen"},
                "jobLocation": {"address": {"addressLocality": "Waiblingen", "postalCode": "71332", "addressCountry": "DE"}}}
        if valid:
            data["validThrough"] = valid
        safe = json.dumps(data).replace("<", "\\u003c")
        job = extract('<script type="application/ld+json">' + safe + "</script>", url, source, req.q)
        if job:
            yield job
        else:
            report["filtered"] += 1
    if not found:
        raise FetchError("unsupported", detail=f"keine Stellenblöcke auf {LIST_URL} ({len(html)} Zeichen, {len(re.findall('<script', html))} Skripte, "
                         f"Zustand {'ja' if 'first_link_href' in html else 'nein'}, Textblöcke {'ja' if 'con-kit-molecule-textBlock' in html else 'nein'})")
