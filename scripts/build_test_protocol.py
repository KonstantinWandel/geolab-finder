#!/usr/bin/env python3
"""Build the review workbook for the colleagues' round.

The first version asked them to check whether the finder retrieves things that are in it. The
retrieval gates already answer that, 58 queries at a time, and a second opinion on it adds little.
What no gate can produce is the thing Erik and Sebastian actually know: which data their work needs
that the index does not hold, and which words they searched with that led nowhere although the data
is there. Those are two different gaps, one in the data and one in the vocabulary, and they are
fixed in completely different ways, so the workbook keeps them apart.

Sheet 1 explains the task. Sheet 2 collects missing data. Sheet 3 collects searches that failed
although the answer exists. Sheet 4 lists what is indexed today, generated from the registry, so
"missing" is judged against the actual contents and not against a guess.

    python scripts/build_test_protocol.py --out deliverables_geodb_datenquellen/Rueckmeldung.xlsx
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "data_sources" / "registry" / "geo_sources.json"
METADATA = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"
BLUE = "1F77B4"
DARK = "2C3E50"

GAPS = [
    ("Was fehlt (Konzept, in Ihren Worten)", 40),
    ("Wofür brauchen Sie es? (Projekt, Fragestellung)", 34),
    ("Räumliche Ebene (Gemeinde, Kreis, …)", 22),
    ("Zeitraum", 16),
    ("Kennen Sie eine Quelle dafür? (Name / Link)", 34),
    ("Im Finder gesucht? Was kam?", 32),
    ("Wichtigkeit (hoch / mittel / niedrig)", 18),
]

VOCAB = [
    ("Suchbegriff, den ich eingegeben habe", 38),
    ("Was ich erwartet hätte", 32),
    ("Was tatsächlich kam", 34),
    ("Habe ich es später doch gefunden? Womit?", 32),
    ("Anmerkung", 34),
]

INTRO = [
    ("Rückmeldung zum GeoDB Geodata Index und zum SOEP Variable Finder", "title"),
    ("", ""),
    (f"Vorbereitet am {date.today().strftime('%d.%m.%Y')} für die gemeinsame Durchsicht.", "italic"),
    ("", ""),
    ("Worum wir Sie bitten", "head"),
    ("Ob der Finder findet, was drin ist, haben wir automatisiert geprüft. Was wir nicht wissen und", ""),
    ("nur von Ihnen erfahren können, ist zweierlei:", ""),
    ("", ""),
    ("1. Welche Daten Sie für Ihre Arbeit brauchen, die es im Index nicht gibt (Blatt 'Was fehlt').", "bold"),
    ("   Blatt 'Was ist schon drin' listet die 33 Quellen, damit Sie nicht etwas vorschlagen, das", ""),
    ("   bereits enthalten ist. Ein Konzept in Ihren Worten genügt, eine Quelle dazu ist willkommen,", ""),
    ("   aber keine Bedingung: die zu finden ist unsere Arbeit, nicht Ihre.", ""),
    ("", ""),
    ("2. Suchbegriffe, mit denen Sie nichts Brauchbares bekommen haben, obwohl es die Daten gibt", "bold"),
    ("   (Blatt 'Suche lief ins Leere'). Das ist der andere Fehlertyp: die Daten sind da, aber unser", ""),
    ("   Werkzeug versteht Ihr Wort dafür nicht. Solche Fälle sind für uns besonders wertvoll, weil", ""),
    ("   wir sie beheben können, ohne eine einzige neue Quelle zu erschließen.", ""),
    ("", ""),
    ("Zum Ausprobieren", "head"),
    ("GeoDB Geodata Index (Geodaten): https://geodb.geolab.soz.uni-bielefeld.de/", ""),
    ("SOEP Variable Finder:            https://soep-faiss.geolab.soz.uni-bielefeld.de/", ""),
    ("", ""),
    ("Beschreiben Sie ruhig in ganzen Sätzen, was Sie suchen; dafür ist die Suche gebaut. Wenn kein", ""),
    ("Treffer sich abhebt, sagt das Werkzeug das inzwischen selbst, und ob dieser Hinweis verständlich", ""),
    ("ist, ist eine der Fragen, die wir Ihnen stellen.", ""),
    ("", ""),
    ("Zeitaufwand: eine halbe Stunde reicht. Lieber fünf gut beschriebene Lücken als dreißig Zeilen.", "bold"),
]


def styled_sheet(workbook: Workbook, title: str, subtitle: str, columns, rows: int = 24):
    ws = workbook.create_sheet(title)
    ws["A1"] = subtitle
    ws["A1"].font = Font(bold=True, size=11, color=BLUE)
    ws["A1"].alignment = Alignment(wrap_text=True)
    for index, (name, width) in enumerate(columns, start=1):
        cell = ws.cell(row=3, column=index, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=DARK)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.row_dimensions[3].height = 32
    for row in range(4, 4 + rows):
        ws.row_dimensions[row].height = 30
        for column in range(1, len(columns) + 1):
            ws.cell(row=row, column=column).alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = ws.cell(row=4, column=1)
    return ws


def indexed_sources():
    """Name, record count and themes per source, straight from what is indexed."""
    rows = json.loads(METADATA.read_text(encoding="utf-8"))
    registry = {s["slug"]: s for s in json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]}
    counts, labels, themes = {}, {}, {}
    for row in rows:
        key = row.get("source_key")
        counts[key] = counts.get(key, 0) + 1
        labels.setdefault(key, row.get("source_label", key))
        if row.get("theme"):
            themes.setdefault(key, set()).add(row["theme"])
    out = []
    for key, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        topic = ", ".join(sorted(themes.get(key, set()))[:4])
        out.append((labels[key], count, topic))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    workbook = Workbook()
    intro = workbook.active
    intro.title = "Anleitung"
    intro.column_dimensions["A"].width = 104
    for index, (text, kind) in enumerate(INTRO, start=1):
        cell = intro.cell(row=index, column=1, value=text)
        cell.font = Font(bold=kind in {"title", "head", "bold"},
                         italic=kind == "italic",
                         size=14 if kind == "title" else 11,
                         color=BLUE if kind in {"title", "head"} else "000000")

    styled_sheet(workbook, "Was fehlt",
                 "Daten, die Sie brauchen und die der Finder nicht kennt. Eine Zeile je Konzept.",
                 GAPS, rows=26)
    styled_sheet(workbook, "Suche lief ins Leere",
                 "Suchbegriffe, die nichts Brauchbares ergaben, obwohl es die Daten gibt.",
                 VOCAB, rows=22)

    ws = styled_sheet(workbook, "Was ist schon drin",
                      "Der heutige Bestand, damit 'fehlt' gegen den tatsächlichen Inhalt beurteilt wird.",
                      [("Quelle", 52), ("Beschreibungen", 16), ("Themen (Auszug)", 62)], rows=0)
    for offset, (name, count, topic) in enumerate(indexed_sources(), start=4):
        ws.cell(row=offset, column=1, value=name)
        ws.cell(row=offset, column=2, value=count)
        ws.cell(row=offset, column=3, value=topic)
        for column in range(1, 4):
            ws.cell(row=offset, column=column).alignment = Alignment(wrap_text=True, vertical="top")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out)
    print(f"geschrieben: {out}")


if __name__ == "__main__":
    main()
