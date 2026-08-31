#!/usr/bin/env python3
"""Build the keyword-test workbook for the colleagues' review round.

Kerstin asked for a list of keywords to be tried and the outcome written down, as the basis for a
joint discussion. This produces the workbook they fill in: instructions on the first sheet, one
sheet per finder with the keywords prepared, and empty columns for what actually came back.

The keywords are not a random list. They are three deliberate groups, so the round produces
comparable evidence rather than impressions:
  * "leicht": the concept is named the way the sources name it. These should simply work.
  * "umschrieben": the concept is described in ordinary words. This is what the tool is for and
    where it is worth knowing how it holds up.
  * "nicht im Index": Germany does not publish this regionally at all. These check whether the
    tool admits it, and whether the note about a flat result field is believed.

    python scripts/build_test_protocol.py --out deliverables_geodb_datenquellen/Stichwort-Test.xlsx
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BLUE = "1F77B4"

GEODB = [
    ("leicht", "Krankenhausbetten je Einwohner"),
    ("leicht", "Arbeitslosenquote auf Kreisebene"),
    ("leicht", "Breitbandverfügbarkeit auf Gemeindeebene"),
    ("leicht", "Bevölkerungsdichte"),
    ("leicht", "Kita-Betreuungsquote unter drei Jahren"),
    ("leicht", "Bodenrichtwerte"),
    ("leicht", "Wahlbeteiligung Bundestagswahl"),
    ("leicht", "Pflegeheime und Pflegebedürftige"),
    ("leicht", "Bruttoinlandsprodukt je Einwohner"),
    ("leicht", "Krankenhäuser"),
    ("umschrieben", "wo müssen Menschen am weitesten zum Arzt fahren"),
    ("umschrieben", "Gegenden, in denen viele Menschen von Sozialleistungen leben"),
    ("umschrieben", "wo ziehen mehr Leute weg als hin"),
    ("umschrieben", "wie teuer ist das Wohnen dort"),
    ("umschrieben", "Regionen mit schlechter Internetversorgung"),
    ("umschrieben", "gibt es hier genug Kita-Plätze"),
    ("umschrieben", "wie grün ist die Gemeinde"),
    ("umschrieben", "Orte, an denen kaum junge Familien wohnen"),
    ("umschrieben", "wie stark hängt eine Region an der Industrie"),
    ("umschrieben", "Erreichbarkeit von Apotheken im ländlichen Raum"),
    ("umschrieben", "Verkehrsunfälle mit Radfahrern"),
    ("umschrieben", "Lärmbelastung an Hauptstraßen"),
    ("umschrieben", "Anteil erneuerbarer Energien"),
    ("umschrieben", "Schulabbrecher"),
    ("umschrieben", "Zahl der Studierenden je Hochschulstandort"),
    ("nicht im Index", "Anteil vegetarisch lebender Personen"),
    ("nicht im Index", "Zahl der Parkbänke je Gemeinde"),
    ("nicht im Index", "Einsamkeit der Bevölkerung"),
    ("nicht im Index", "Vertrauen in die Nachbarschaft"),
    ("nicht im Index", "Arbeitslosigkeit in Frankreich"),
]

SOEP = [
    ("leicht", "Nettoerwerbseinkommen im letzten Monat"),
    ("leicht", "Lebenszufriedenheit"),
    ("leicht", "höchster Schulabschluss"),
    ("leicht", "Migrationshintergrund"),
    ("leicht", "tatsächliche Arbeitszeit pro Woche"),
    ("leicht", "Familienstand"),
    ("leicht", "Haushaltsnettoeinkommen"),
    ("leicht", "Gesundheitszustand"),
    ("umschrieben", "wie zufrieden sind die Leute mit ihrem Leben"),
    ("umschrieben", "wie viel verdient jemand netto im Monat"),
    ("umschrieben", "Bildungsabschluss der Eltern"),
    ("umschrieben", "Sorgen um die eigene wirtschaftliche Lage"),
    ("umschrieben", "Vertrauen in andere Menschen"),
    ("umschrieben", "wie oft wird Fleisch gegessen"),
    ("umschrieben", "Einstellung zu Geschlechterrollen"),
    ("umschrieben", "Wohnort in Ost- oder Westdeutschland"),
    ("nicht im Index", "Lieblingsfarbe der Befragten"),
    ("nicht im Index", "Zahl der Haustiere im Haushalt"),
]

COLUMNS = [
    ("Gruppe", 14), ("Stichwort", 42), ("Was ich erwartet habe", 32),
    ("Treffer 1", 34), ("Treffer 2", 34), ("Treffer 3", 34),
    ("Wohin führte der Link von Treffer 1?", 30),
    ("Brauchbar? (ja / teilweise / nein)", 20), ("Anmerkung", 46),
]

INSTRUCTIONS = [
    ("Stichwort-Test der GeoLAB-Finder", True),
    ("", False),
    (f"Vorbereitet am {date.today().strftime('%d.%m.%Y')} für die gemeinsame Durchsicht.", False),
    ("", False),
    ("Worum es geht", True),
    ("Die beiden Finder durchsuchen Beschreibungen von Daten, nicht die Daten selbst. Ein Treffer", False),
    ("ist also die Beschreibung eines Indikators, einer Tabelle oder eines Datensatzes, und der Link", False),
    ("führt zu der Stelle, die die Daten wirklich hält. Uns interessiert, ob die richtigen Sachen", False),
    ("gefunden werden und ob man von dort aus wirklich an die Zahlen kommt.", False),
    ("", False),
    ("So gehen Sie vor", True),
    ("1. Blatt 'GeoDB' und Blatt 'SOEP' nacheinander durchgehen, die Adressen stehen dort oben.", False),
    ("2. Stichwort eintippen, suchen, die ersten drei Treffer kurz notieren (Name genügt).", False),
    ("3. Beim ersten Treffer den Link anklicken: landen Sie direkt bei der Sache, auf einer", False),
    ("   Übersichtsseite, oder auf einer Startseite, wo Sie erneut suchen müssen?", False),
    ("4. Spalte 'Brauchbar' ausfüllen und alles, was auffällt, in die Anmerkung.", False),
    ("", False),
    ("Was die Gruppen bedeuten", True),
    ("leicht: der Begriff heißt bei den Quellen genauso. Sollte einfach klappen.", False),
    ("umschrieben: mit eigenen Worten beschrieben. Dafür ist das Werkzeug gedacht.", False),
    ("nicht im Index: das gibt es für Deutschland regional gar nicht. Hier ist die Frage, ob das", False),
    ("Werkzeug es zugibt: es zeigt dann einen Hinweis, dass sich kein Treffer abhebt.", False),
    ("", False),
    ("Gern eigene Stichworte unten anhängen, die Zeilen sind nicht begrenzt.", False),
]


def sheet_for(workbook: Workbook, title: str, url: str, rows: list[tuple[str, str]]) -> None:
    ws = workbook.create_sheet(title)
    ws["A1"] = f"{title}: {url}"
    ws["A1"].font = Font(bold=True, size=12, color=BLUE)
    ws["A2"] = "Stichwort eintippen, suchen, die ersten drei Treffer notieren, dann den Link von Treffer 1 prüfen."
    ws["A2"].font = Font(italic=True, size=10)
    header_row = 4
    for index, (name, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=index, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2C3E50")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.row_dimensions[header_row].height = 30
    for offset, (group, keyword) in enumerate(rows, start=header_row + 1):
        ws.cell(row=offset, column=1, value=group)
        ws.cell(row=offset, column=2, value=keyword)
        for column in range(1, len(COLUMNS) + 1):
            ws.cell(row=offset, column=column).alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    workbook = Workbook()
    intro = workbook.active
    intro.title = "Anleitung"
    intro.column_dimensions["A"].width = 100
    for index, (text, bold) in enumerate(INSTRUCTIONS, start=1):
        cell = intro.cell(row=index, column=1, value=text)
        cell.font = Font(bold=bold, size=13 if (bold and index == 1) else 11,
                         color=BLUE if index == 1 else "000000")

    sheet_for(workbook, "GeoDB", "https://geodb.geolab.soz.uni-bielefeld.de/", GEODB)
    sheet_for(workbook, "SOEP", "https://soep-faiss.geolab.soz.uni-bielefeld.de/", SOEP)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out)
    print(f"geschrieben: {out}  ({len(GEODB)} GeoDB-Stichworte, {len(SOEP)} SOEP-Stichworte)")


if __name__ == "__main__":
    main()
