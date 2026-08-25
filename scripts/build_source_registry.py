#!/usr/bin/env python3
"""Flatten `Geospatial_Data_Sources.xlsx` into a machine-readable source registry and
scaffold the `data_sources/` drop tree.

The workbook is a coverage matrix: one row per external German geo-referenced data
portal, one column per spatial level / thematic indicator, marked with a `1`. The
portal URL lives in the Excel HYPERLINK of the name cell, not in any text column, so
`pandas` alone cannot see it and `openpyxl` is required.

Outputs (all repo-relative, nothing in a temp/scratch dir):
  data_sources/registry/geo_sources.json   canonical, committed
  data_sources/registry/geo_sources.csv    human-readable twin (git-ignored: *.csv)
  data_sources/<NN>-<slug>/SOURCE.md       per-source brief (written once, then yours)
  data_sources/<NN>-<slug>/raw/            where the downloaded catalogue files go

Run:
  python scripts/build_source_registry.py            # registry + scaffold
  python scripts/build_source_registry.py --no-scaffold
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = REPO_ROOT / "Geospatial_Data_Sources.xlsx"
DEFAULT_OUT_DIR = REPO_ROOT / "data_sources"
SHEET = "Tabelle1"

# Loud assertion: the wrong workbook must fail instead of silently producing a
# half-registry (see the workspace rule on sample definitions).
EXPECTED_SOURCES = 26

# Column blocks, by header text (trailing spaces in the workbook are stripped first).
NAME_COL = "Datenquellen"
TEMPORAL_COLS = ["start month", "start year", "endmonth", "endyear", "Turnus", "Kommentar"]
ACCESS_COLS = ["Direkter Download", "GUI", "API", "Karte", "Beantragung"]
SPATIAL_COLS = [
    "Bundesland",
    "Regierungsbezirke",
    "Kreise & kreisfreie Städte",
    "Gemeinden und Verbandsgemeinden",
    "Bezirke",
    "Bezirksregionen / Ortsteile",
    "PLZ",
    "Adressen / Koordinaten",
    "weitere räumliche Gliederungen",
]

# The workbook gives topics no visual hierarchy (no bold, fill, or merge distinguishes
# a group header from its members), so the grouping is declared here. Everything after
# a group header up to the next one is a subtopic of it. `Steuern` and `Förderungen`
# sit after the election columns but are not election indicators, so they are treated
# as their own groups rather than silently parented to `Politik`.
TOPIC_GROUPS = {
    "Arbeitsmarkt & Beschäftigung",
    "Bauen / Wohnen",
    "Bevölkerung",
    "Bildung",
    "Digitalisierung",
    "Finanzen",
    "Flächennutzung",
    "Gender",
    "Gesundheit",
    "Kinder und Jugend",
    "Kultur",
    "Migration",
    "Nachhaltigkeit",
    "Religion",
    "Soziales",
    "Sport",
    "Tourismus",
    "Ver- und Entsorgung",
    "Verkehr / Mobilität",
    "Politik",
    "Steuern",
    "Förderungen",
    "Wirtschaft und Unternehmen",
}

ACCESS_LABEL = {
    "Direkter Download": "direct file download",
    "GUI": "web UI / search form only",
    "API": "machine-readable API",
    "Karte": "interactive map viewer",
    "Beantragung": "on request / registration needed",
}

MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}

# Some workbook names are long or have been renamed in place; pin their folder slug so a
# rename in Tabelle1 does not orphan an existing data_sources/<NN>-<slug>/ folder.
SLUG_OVERRIDES = {
    "Bundes-Klinik-Atlas (vormals Fachärztesuche - Weisse Liste)": "bundes-klinik-atlas",
}

UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return re.sub(r"\s+", " ", text)


def as_year(value: Any) -> int | None:
    text = clean(value)
    if not text:
        return None
    match = re.search(r"(?:19|20)\d{2}", text)
    return int(match.group(0)) if match else None


def slugify(name: str) -> str:
    text = name.lower().strip()
    for umlaut, replacement in UMLAUTS.items():
        text = text.replace(umlaut, replacement)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text)[:48]


def read_workbook(path: Path) -> List[Dict[str, Any]]:
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[SHEET]

    headers = [clean(cell.value) for cell in sheet[1]]
    index_of = {}
    for position, header in enumerate(headers):
        index_of.setdefault(header, position)

    # Topic columns: everything to the right of the spatial block.
    first_topic = max(index_of[column] for column in SPATIAL_COLS) + 1
    topic_columns: List[Dict[str, str]] = []
    current_group = ""
    for position in range(first_topic, len(headers)):
        header = headers[position]
        if not header:
            continue
        # A group header counts only at its FIRST occurrence: `Bildung` appears twice
        # (own group, and again as a sustainability sub-indicator), and a name-only test
        # would silently re-parent every following Nachhaltigkeit column to Bildung.
        if header in TOPIC_GROUPS and index_of[header] == position:
            current_group = header
            topic_columns.append({"position": position, "group": header, "topic": header, "is_group": True})
        else:
            topic_columns.append({"position": position, "group": current_group, "topic": header, "is_group": False})

    records: List[Dict[str, Any]] = []
    for row_number in range(2, sheet.max_row + 1):
        cells = sheet[row_number]
        name_cell = cells[index_of[NAME_COL]]
        name = clean(name_cell.value)
        if not name:
            continue

        def marked(column: str) -> bool:
            return bool(clean(cells[index_of[column]].value))

        topics: List[Dict[str, str]] = []
        for column in topic_columns:
            if clean(cells[column["position"]].value):
                topics.append({"group": column["group"], "topic": column["topic"]})

        access = [ACCESS_LABEL[column] for column in ACCESS_COLS if marked(column)]
        spatial = [column for column in SPATIAL_COLS if marked(column)]

        records.append(
            {
                "name": name,
                "slug": SLUG_OVERRIDES.get(name, slugify(name)),
                "url": name_cell.hyperlink.target if name_cell.hyperlink else "",
                "excel_row": row_number,
                "provider": "",  # filled by hand in SOURCE.md; not in the workbook
                "access_modes": access,
                "access_flags": {column: marked(column) for column in ACCESS_COLS},
                "spatial_levels": spatial,
                "topic_groups": sorted({t["group"] for t in topics if t["group"]}),
                "topics": topics,
                "topic_labels": [t["topic"] for t in topics],
                "coverage_start_month": MONTHS.get(clean(cells[index_of["start month"]].value).lower()),
                "coverage_start_year": as_year(cells[index_of["start year"]].value),
                "coverage_end_month": MONTHS.get(clean(cells[index_of["endmonth"]].value).lower()),
                "coverage_end_year": as_year(cells[index_of["endyear"]].value),
                "update_frequency": clean(cells[index_of["Turnus"]].value),
                "note": clean(cells[index_of["Kommentar"]].value),
            }
        )

    return records


def write_registry(records: List[Dict[str, Any]], out_dir: Path) -> Dict[str, Path]:
    registry_dir = out_dir / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)

    json_path = registry_dir / "geo_sources.json"
    payload = {
        "schema_version": 1,
        "workbook": "Geospatial_Data_Sources.xlsx",
        "n_sources": len(records),
        "sources": records,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = registry_dir / "geo_sources.csv"
    import csv as _csv

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = _csv.writer(handle)
        writer.writerow(
            ["slug", "name", "url", "access_modes", "spatial_levels", "topic_groups",
             "n_topics", "coverage_start_year", "coverage_end_year", "update_frequency", "note"]
        )
        for record in records:
            writer.writerow(
                [
                    record["slug"], record["name"], record["url"],
                    "; ".join(record["access_modes"]),
                    "; ".join(record["spatial_levels"]),
                    "; ".join(record["topic_groups"]),
                    len(record["topics"]),
                    record["coverage_start_year"] or "",
                    record["coverage_end_year"] or "",
                    record["update_frequency"], record["note"],
                ]
            )

    return {"json": json_path, "csv": csv_path}


SOURCE_MD = """# {name}

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row {excel_row}).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** {url}
- **Access:** {access}
- **Spatial levels:** {spatial}
- **Temporal coverage:** {coverage}
- **Update frequency:** {frequency}
- **Workbook note:** {note}
- **Topic groups:** {groups}

## Topics marked in the workbook

{topics}

## What to drop in `raw/`

Anything that lists **what indicators this portal offers**, at the finest granularity
you can get without downloading the actual data:

- an indicator/variable overview (`.xlsx`, `.csv`, `.pdf` codebook, `.json`)
- an API catalogue response (e.g. the list-of-tables endpoint saved as `.json`)
- a saved copy of the portal's indicator/theme browse page (`.html`) if there is no
  downloadable list
- the metadata/documentation PDF that names and defines the indicators

Not needed: the measurement values themselves. The finder indexes *descriptions* and
sends the researcher to this portal.

Name files descriptively (`indicator-overview-2025.xlsx`, `api-catalogue-2026-08.json`)
and leave them as downloaded, no manual cleaning.

## Manual notes

- Provider / publisher:
- Licence / terms of use:
- Identifier scheme (indicator codes?):
- Deep-link pattern to a single indicator (if any):
- Status:
"""


def scaffold(records: List[Dict[str, Any]], out_dir: Path) -> List[Path]:
    created: List[Path] = []
    for position, record in enumerate(records, start=1):
        folder = out_dir / f"{position:02d}-{record['slug']}"
        raw = folder / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        gitkeep = raw / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

        # Machine-readable sidecar: always refreshed from the workbook.
        (folder / "source_meta.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        brief = folder / "SOURCE.md"
        if brief.exists():
            continue

        by_group: Dict[str, List[str]] = {}
        for topic in record["topics"]:
            by_group.setdefault(topic["group"] or "(ungrouped)", []).append(topic["topic"])
        topic_lines = (
            "\n".join(
                f"- **{group}**: " + ", ".join(t for t in items if t != group)
                if [t for t in items if t != group]
                else f"- **{group}**"
                for group, items in by_group.items()
            )
            or "_none marked_"
        )

        start = record["coverage_start_year"]
        end = record["coverage_end_year"]
        coverage = f"{start or '?'}–{end or '?'}" if (start or end) else "not stated"

        brief.write_text(
            SOURCE_MD.format(
                name=record["name"],
                excel_row=record["excel_row"],
                url=record["url"] or "_missing in workbook_",
                access=", ".join(record["access_modes"]) or "not stated",
                spatial=", ".join(record["spatial_levels"]) or "not stated",
                coverage=coverage,
                frequency=record["update_frequency"] or "not stated",
                note=record["note"] or "none",
                groups=", ".join(record["topic_groups"]) or "none",
                topics=topic_lines,
            ),
            encoding="utf-8",
        )
        created.append(brief)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--no-scaffold", action="store_true", help="write the registry only")
    parser.add_argument("--expected", type=int, default=EXPECTED_SOURCES)
    args = parser.parse_args()

    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        raise FileNotFoundError(workbook_path)

    records = read_workbook(workbook_path)
    if args.expected and len(records) != args.expected:
        raise SystemExit(
            f"Expected {args.expected} data sources in {workbook_path.name}, got {len(records)}. "
            "If the workbook genuinely grew, re-run with --expected N and update EXPECTED_SOURCES."
        )

    missing_url = [r["name"] for r in records if not r["url"]]
    out_dir = Path(args.out_dir)
    paths = write_registry(records, out_dir)
    created = [] if args.no_scaffold else scaffold(records, out_dir)

    print(json.dumps(
        {
            "sources": len(records),
            "registry": {key: str(value) for key, value in paths.items()},
            "source_folders": 0 if args.no_scaffold else len(records),
            "new_SOURCE_md": len(created),
            "sources_without_url": missing_url,
        },
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
