#!/usr/bin/env python3
"""Look for records whose facets contradict what their own text says.

The raster defect was of this shape: the label said "(Gitterzelle)" while `spatial_levels` never
mentioned a grid, so the filter could not reach the record. This audit generalises that check to
every spatial level and to the other facets a user filters on, and prints what it finds rather
than fixing anything: each hit needs a human decision about which side is wrong.

    python scripts/audit_geodb_facets.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"

# level -> what the text would say if the record were on that level
CLAIMS = {
    "Rasterzellen": r"gitterzelle|rasterzelle|\braster\b|gitter für deutschland|100\s?m[\s-]?grid",
    "Gemeinden": r"\bgemeinde|gemeindeebene|kommunal|municipal",
    "Kreise": r"\bkreis(e|en)?\b|landkreis|kreisfrei|nuts3|district",
    "Bundesländer": r"bundesland|bundesländer|nuts1|federal state",
    "PLZ": r"\bplz\b|postleitzahl|postcode",
    "Ortsteile": r"ortsteil|stadtteil|bezirksregion",
    "Bezirke": r"\bbezirk(e|en)?\b",
    "Bundestagswahlkreise": r"wahlkreis",
    "Adressen/Koordinaten": r"adresse|koordinate|standort|punktdaten|geokodiert",
}
# words that make a level mention meaningless (a comparison, not a coverage claim)
NEGATED = re.compile(r"nicht auf|keine? angaben|unterhalb der|oberhalb der", re.I)


def text_of(row: Dict[str, Any]) -> str:
    return " ".join(str(row.get(field) or "") for field in
                    ("label", "dataset_label", "rich_description", "api_hint"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata", default=str(DEFAULT))
    parser.add_argument("--examples", type=int, default=3)
    args = parser.parse_args()

    rows: List[Dict[str, Any]] = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    print(f"{len(rows)} Datensätze aus {args.metadata}\n")

    # 1. the raster defect's shape: the text claims a level the facets do not carry
    print("== Text nennt eine Ebene, die Facette führt sie nicht")
    for level, pattern in CLAIMS.items():
        offenders = [
            row for row in rows
            if re.search(pattern, text_of(row), re.I)
            and not NEGATED.search(text_of(row))
            and level not in (row.get("spatial_levels") or [])
            and level not in (row.get("nuts_levels") or [])
        ]
        if not offenders:
            continue
        by_source = collections.Counter(row.get("source_key") for row in offenders)
        print(f"  {level:<22} {len(offenders):>5} Datensätze  {dict(by_source.most_common(4))}")
        for row in offenders[: args.examples]:
            print(f"      - [{row.get('source_key')}] {str(row.get('label'))[:58]} "
                  f"-> {row.get('spatial_levels')}")

    # 2. facets that are missing outright
    print("\n== Fehlende Facetten")
    for field, label in (("spatial_levels", "ohne räumliche Ebene"),
                         ("theme", "ohne Thema"),
                         ("available_years_text", "ohne Jahresangabe")):
        missing = [row for row in rows if not row.get(field)]
        if missing:
            counts = collections.Counter(row.get("source_key") for row in missing)
            print(f"  {label:<24} {len(missing):>5}  {dict(counts.most_common(5))}")

    # 3. a source whose records all carry exactly one level set is suspicious: either it really
    #    publishes one geography, or the level was hard-coded once and never differentiated
    print("\n== Quellen mit genau einer Ebenen-Kombination für alle Datensätze")
    per_source: Dict[str, set] = collections.defaultdict(set)
    for row in rows:
        per_source[row.get("source_key")].add(tuple(sorted(row.get("spatial_levels") or [])))
    for source, combos in sorted(per_source.items()):
        count = sum(1 for row in rows if row.get("source_key") == source)
        if len(combos) == 1 and count >= 20:
            print(f"  {source:<22} {count:>5} Datensätze  {list(combos)[0]}")

    # 4. link precision, the other facet a user reads as a promise
    print("\n== Verlinkungstiefe")
    print(" ", dict(collections.Counter(row.get("link_level") for row in rows).most_common()))
    unverified = [row for row in rows if row.get("link_verified") is False]
    if unverified:
        print(f"  ungeprüfte Links: {len(unverified)} "
              f"{dict(collections.Counter(r.get('source_key') for r in unverified).most_common(5))}")


if __name__ == "__main__":
    main()
