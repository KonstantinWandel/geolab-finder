#!/usr/bin/env python3
"""Schreibt die Begriffe des Merkmalsregisters in eine kleine Datei für den Finder.

    python3 scripts/build_measure_concepts.py

Warum das hier steht und nicht im Register: der Finder ist eine eigene Anwendung auf einem
eigenen Host. Er soll bei einem Treffer sagen können "von dieser Größe gibt es 64 Fassungen aus
9 Quellen, und sie messen nicht alle dasselbe", und dafür braucht er nur fünfzehn Zeilen, nicht
die 455 KB aller Fassungen.

Entscheidend ist, dass er die Zugehörigkeit **mit derselben geschriebenen Regel** entscheidet wie
das Register selbst. Eine zweite, ähnlich gemeinte Regel wäre genau der Weg, auf dem die beiden
Seiten irgendwann verschiedene Antworten geben. Die Regel reist deshalb mit, statt nachgebaut zu
werden.

Erzeugtes Artefakt, nicht von Hand bearbeiten.
"""
from __future__ import annotations

import json
import pathlib

HIER = pathlib.Path(__file__).resolve().parent
WURZEL = HIER.parent
QUELLE = WURZEL.parent / "geolab_regiohub" / "tools" / "measure-register" / "register.json"
ZIEL = WURZEL / "frontend" / "public" / "measure_concepts.json"
REGISTER_URL = "https://geolab.soz.uni-bielefeld.de/tools/measure-register/"


def main() -> None:
    if not QUELLE.exists():
        raise SystemExit(f"register.json fehlt unter {QUELLE}; erst den Registerbauer laufen lassen")
    reg = json.loads(QUELLE.read_text(encoding="utf-8"))
    begriffe = []
    for b in reg.get("begriffe", []):
        varianten = b.get("varianten") or []
        nenner = sorted({(v.get("nenner") or "").strip() for v in varianten if (v.get("nenner") or "").strip()})
        begriffe.append({
            "id": b["id"],
            "title": b.get("titel") or b["id"],
            "de": b.get("titel_de") or "",
            "rule": b.get("regel") or "",
            "not": b.get("regel_aus") or "",
            "n": len(varianten),
            "sources": len(b.get("quellen") or []),
            "denominators": len(nenner),
        })
    if not begriffe:
        raise SystemExit("keine Begriffe gefunden, das kann nicht stimmen")
    aus = {"built": reg.get("gebaut", ""), "url": REGISTER_URL, "concepts": begriffe}
    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text(json.dumps(aus, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(begriffe)} Begriffe -> {ZIEL} ({ZIEL.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
