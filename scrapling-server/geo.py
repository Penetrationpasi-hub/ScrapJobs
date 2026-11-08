"""Distances for place texts in result lists (same data and rules as netlify/lib/umkreis.mjs).

Only used to decide which listed ads are worth a detail request; the exact radius check still happens
on the verified JobPosting location downstream.
"""
import math
import re
from functools import lru_cache
from pathlib import Path

REGION_WORDS = {
    "badenwuerttemberg", "bayern", "brandenburg", "hessen", "mecklenburgvorpommern", "niedersachsen",
    "nordrheinwestfalen", "rheinlandpfalz", "saarland", "sachsen", "sachsenanhalt", "schleswigholstein",
    "thueringen", "wuerttemberg", "de", "deu", "deutschland", "germany",
}


def norm(text):
    value = text.lower()
    for char, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        value = value.replace(char, replacement)
    return re.sub(r"[^a-z0-9]+", "", value)


@lru_cache(maxsize=1)
def data():
    folder = Path(__file__).parent
    plz = {}
    for line in (folder / "plz_de.txt").read_text(encoding="utf-8").splitlines():
        code, lat, lon = line.split("|")
        plz[code] = (float(lat), float(lon))
    by_key = {}
    for line in (folder / "orte_de.txt").read_text(encoding="utf-8").splitlines():
        name, population, codes, *rest = line.split("|")
        points = [plz[code] for code in codes.split(" ") if code in plz]
        if not points:
            continue
        ort = {"name": name, "population": int(population or 0), "points": points}
        for key in {norm(name), norm(rest[0] if rest and rest[0] else name)}:
            by_key.setdefault(key, []).append(ort)
    return plz, by_key


def km(a, b):
    rad = math.pi / 180
    d_lat, d_lon = (b[0] - a[0]) * rad, (b[1] - a[1]) * rad
    h = math.sin(d_lat / 2) ** 2 + math.cos(a[0] * rad) * math.cos(b[0] * rad) * math.sin(d_lon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def resolve(text):
    """Text → list of points ([one] for a postcode, all postcodes of a municipality otherwise) or None."""
    text = (text or "").strip()
    if not text:
        return None
    plz, by_key = data()
    if code := re.search(r"\b\d{5}\b", text):
        return [plz[code.group(0)]] if code.group(0) in plz else None
    name = text.split(",")[0].strip()
    candidates = by_key.get(norm(name), [])
    exact = [ort for ort in candidates if ort["name"].lower() == name.lower()]
    pool = exact or candidates
    return max(pool, key=lambda ort: ort["population"])["points"] if pool else None


def center(text):
    points = resolve(text)
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def distance_km(origin, place_text):
    """Distance to the nearest site named in the text, None if no site can be resolved."""
    text = re.sub(r"\([^)]*\)", " ", place_text or "")
    best = None
    for site in (part.strip() for part in re.split(r"\s/\s|[;|]", text)):
        if not site:
            continue
        if re.search(r"\b\d{5}\b", site):
            candidates = [site]
        else:
            candidates = []
            for part in re.split(r"[,/]|\s[-–]\s", site):
                words = part.strip().split()
                while words and norm(words[-1]) in REGION_WORDS:
                    words.pop()
                joined = " ".join(words)
                if joined and norm(joined) not in REGION_WORDS:
                    candidates.append(joined)
        for candidate in candidates:
            points = resolve(candidate)
            if points:
                distance = min(km(origin, point) for point in points)
                best = distance if best is None else min(best, distance)
    return best


def in_range(origin, place_text, radius_km):
    """True/False when the listed place can be resolved, None when unknown or multi-site ("…+")."""
    text = (place_text or "").strip()
    if not text or text.endswith("+"):
        return None
    distance = distance_km(origin, text)
    return None if distance is None else distance <= radius_km
