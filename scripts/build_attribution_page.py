#!/usr/bin/env python3
"""Generate the public data-source and attribution page for the GeoLAB site.

The finders are public and serve descriptions derived from other people's catalogues. Several
of those require attribution by their own terms (the Breitbandatlas explicitly, the grid via
BKG, the Datenguide-derived material under dl-de/by-2-0), so the attribution list has to exist
and has to stay in step with what is actually indexed. It is therefore generated from the
registry plus the built metadata, never hand-maintained.

Run:
  python scripts/build_attribution_page.py --out ../geolab_regiohub/data-sources.qmd
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "data_sources" / "registry" / "geo_sources.json"
METADATA = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"
INKAR = REPO_ROOT / "soep_metadata_output" / "inkar_metadata_2025.json"

# Terms that the source itself imposes on reuse of its information. Kept explicit rather than
# guessed: an empty entry means "no specific term found, standard citation applies".
TERMS: Dict[str, str] = {
    "regionalatlas": "© Statistische Ämter des Bundes und der Länder. Data licence Germany, attribution.",
    "regionalstatistik": "© Statistische Ämter des Bundes und der Länder (Regionaldatenbank Deutschland). "
                         "Metadata derived from the Datenguide project under Data licence Germany, "
                         "attribution, version 2.0 (dl-de/by-2-0).",
    "genesis_bund": "© Statistisches Bundesamt (Destatis), GENESIS-Online.",
    "zensus2022": "© Statistische Ämter des Bundes und der Länder, Zensus 2022.",
    "inkar": "© Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), INKAR. "
             "Used under the BBSR terms of use.",
    "deutschlandatlas": "© Statistisches Bundesamt (Destatis) / BBSR, Deutschlandatlas.",
    "breitband": "Source: Breitbandatlas | Gigabit-Grundbuch (https://gigabitgrundbuch.bund.de). "
                 "The grid geometry contains information from the Bundesamt für Kartographie und "
                 "Geodäsie (BKG), used under the BKG terms of use.",
    "unfallatlas": "© Statistische Ämter des Bundes und der Länder, Unfallatlas.",
    "ba_strukturdaten": "© Statistik der Bundesagentur für Arbeit.",
    "ba_arbeitsmarktreport": "© Statistik der Bundesagentur für Arbeit.",
    "ba_arbeitsmarkt_kommunal": "© Statistik der Bundesagentur für Arbeit.",
    "btw21_strukturdaten": "© Die Bundeswahlleiterin, Wiesbaden.",
    "migration_integration": "© Statistisches Bundesamt (Destatis).",
    "gba_qualitaetsbericht": "© Gemeinsamer Bundesausschuss (G-BA), structured quality reports.",
    "bundes_klinik_atlas": "© IQTIG / Bundes-Klinik-Atlas, open data export.",
    "laendermonitor": "© Bertelsmann Stiftung, Ländermonitor Frühkindliche Bildungssysteme.",
    "hochschulkompass": "© Hochschulrektorenkonferenz (HRK), Hochschulkompass.",
    "opendata_oepnv": "© the respective transport associations via opendata-oepnv.de.",
    "german_companies": "© Implisense GmbH, German Company Data (accessed through RapidAPI).",
    "geoportal": "Portal descriptions compiled by the GeoLAB project; the linked portals remain "
                 "the source of the data itself.",
    "soep": "SOEP-Core variable metadata © DIW Berlin / SOEP. Structural metadata from "
            "paneldata.org. No microdata is served.",
}

HEADER = """---
title: "Data sources and attribution"
---

The GeoLAB finders are **metadata search tools**. They index descriptions of data that other
institutions publish, and every hit links out to the portal that holds the data. No measurement
values and no microdata are stored in or served by the finders.

- [GeoDB Geodata Index](https://geodb.geolab.soz.uni-bielefeld.de/): {geodb_rows} indicator,
  table and dataset descriptions from {geodb_sources} German georeferenced data sources.
- [SOEP Variable Finder](https://soep-faiss.geolab.soz.uni-bielefeld.de/): survey-variable
  metadata of the Socio-Economic Panel.

Where a source requires attribution for the reuse of its information, that wording is reproduced
below. Please cite the original source, not the finder, when you use the data itself.

*Generated on {stamp} from the project's source registry, so this list matches what is actually
indexed.*

"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    registry = {entry["slug"]: entry for entry in json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]}
    records = json.loads(METADATA.read_text(encoding="utf-8"))
    counts = Counter(record["source_key"] for record in records)
    labels: Dict[str, str] = {}
    urls: Dict[str, str] = {}
    for record in records:
        key = record["source_key"]
        labels.setdefault(key, record.get("source_label", key))
        urls.setdefault(key, record.get("selector_url") or record.get("source_url") or "")
    if INKAR.exists():
        counts["inkar"] = len(json.loads(INKAR.read_text(encoding="utf-8")))
        labels["inkar"] = "INKAR (BBSR)"
        urls["inkar"] = "https://www.inkar.de/"

    lines: List[str] = [HEADER.format(
        geodb_rows=f"{sum(counts.values()):,}".replace(",", " "),
        geodb_sources=len([k for k in counts if k != "soep"]),
        stamp=args.date,
    )]

    lines.append("## Indexed sources\n")
    lines.append("| Source | Records | Terms of use / attribution |")
    lines.append("|---|---:|---|")
    for key, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        label = labels.get(key, key)
        url = urls.get(key, "")
        name = f"[{label}]({url})" if url else label
        lines.append(f"| {name} | {count} | {TERMS.get(key, 'Standard citation of the source applies.')} |")

    lines.append("\n## Portals listed without an indicator catalogue\n")
    lines.append("Some portals publish no machine-readable list of what they contain. They are "
                 "described at portal level so a concept search still routes to them:\n")
    for slug, entry in sorted(registry.items(), key=lambda kv: kv[1]["name"]):
        if entry["url"]:
            lines.append(f"- [{entry['name']}]({entry['url']})")

    lines.append("\n## Software and citation\n")
    lines.append("The finders are open source (MIT) and archived on Zenodo. Retrieval uses the "
                 "multilingual `intfloat/multilingual-e5-large-instruct` bi-encoder (MIT) with the "
                 "`BAAI/bge-reranker-base` cross-encoder (Apache-2.0).\n")
    lines.append("- Code: <https://github.com/KonstantinWandel/geolab-finder> and "
                 "<https://github.com/KonstantinWandel/soep-variable-finder>\n")

    out = Path(args.out)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(counts)} sources, {sum(counts.values())} records)")


if __name__ == "__main__":
    main()
