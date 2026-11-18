"""Prueft den letzten Lauf in laeufe.csv: jede Quelle ohne Stellen macht den Lauf rot.

    python pruefen.py ../laeufe.csv ohne_stellen_ok.json

Quellen auf der Ausnahmeliste (dauerhaft nicht lauffaehig) zaehlen nicht.
Liefert eine Ausnahme-Quelle wieder Stellen, kommt ein Hinweis, sie von der
Liste zu streichen. Die Tabelle landet in $GITHUB_STEP_SUMMARY.
Exit 1, wenn eine nicht ausgenommene Quelle keine Stellen geliefert hat.
"""
import csv
import json
import os
import sys


def lies(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def pruefe(rows, ausnahmen):
    """-> (fehler, entbehrlich, laufzeit). Nur die Zeilen des juengsten Laufs zaehlen."""
    if not rows:
        return [], [], None
    lauf = max(r["lauf"] for r in rows)
    jetzt = [r for r in rows if r["lauf"] == lauf]
    fehler, entbehrlich = [], []
    for r in sorted(jetzt, key=lambda r: r["label"].casefold()):
        leer = int(r["stellen_lauf"] or 0) == 0
        if leer and r["quelle"] not in ausnahmen:
            fehler.append(r)
        elif not leer and r["quelle"] in ausnahmen:
            entbehrlich.append(r)
    return fehler, entbehrlich, lauf


def seit(rows, quelle):
    """Laeufe ohne Ergebnis in Folge (neueste zuerst gezaehlt)."""
    n = 0
    for r in sorted((r for r in rows if r["quelle"] == quelle), key=lambda r: r["lauf"], reverse=True):
        if int(r["stellen_lauf"] or 0) != 0:
            break
        n += 1
    return n


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    rows = lies(argv[0] if argv else "../laeufe.csv")
    with open(argv[1] if len(argv) > 1 else "ohne_stellen_ok.json", encoding="utf-8") as fh:
        ausnahmen = json.load(fh)
    fehler, entbehrlich, lauf = pruefe(rows, ausnahmen)
    if lauf is None:
        print("::warning::laeufe.csv ist leer, nichts zu prüfen.")
        return 0
    for r in fehler:
        print(f"::error::{r['label']} ({r['quelle']}, Adapter {r['adapter']}): "
              f"{r['status']}, 0 Stellen{' - ' + r['detail'] if r['detail'] else ''}")
    for r in entbehrlich:
        print(f"::notice::{r['label']} liefert wieder Stellen - aus ohne_stellen_ok.json streichen.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## Quellen ohne Stellen (Lauf {lauf[:16].replace('T', ' ')} UTC)\n\n")
            if fehler:
                fh.write("| Arbeitgeber | Schlüssel | Adapter | Status | Läufe in Folge | Detail |\n|---|---|---|---|---|---|\n")
                for r in fehler:
                    fh.write(f"| {r['label']} | {r['quelle']} | {r['adapter']} | {r['status']} | "
                             f"{seit(rows, r['quelle'])} | {r['detail']} |\n")
            else:
                fh.write("Alle Quellen außerhalb der Ausnahmeliste haben Stellen geliefert.\n")
            if entbehrlich:
                fh.write("\nVon der Ausnahmeliste streichen: " + ", ".join(r["quelle"] for r in entbehrlich) + "\n")
    print(f"{len(fehler)} Quelle(n) ohne Stellen (ohne Ausnahmen).")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
