#!/usr/bin/env python3
"""Fetch what the BBSR publishes about INKAR indicators as geo services.

INKAR itself has no address for a single indicator (see CLAUDE.md), so the records link to the
portal. The BBSR does publish a subset of the indicators as WMS layers and as metadata records in
its catalogue service, and those records are harvested into the national Geodatenkatalog, where
each one has a page of its own. That is the closest thing to a per-indicator address that exists,
and this script collects it:

  * WMS GetCapabilities  -> layer name and title per indicator and spatial level
  * CSW GetRecords       -> metadata record id and title per indicator
  * gdk.gdi-de.org       -> which of those records actually resolve nationally (checked, not assumed)

Output: data_sources/22-inkar/raw/geodienste.json, read by scripts/build_inkar_metadata_index.py.

Run:
  python scripts/fetch_inkar_geodienste.py
  python scripts/fetch_inkar_geodienste.py --skip-resolve      # no national catalogue check
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "data_sources" / "22-inkar" / "raw" / "geodienste.json"
WMS = "https://www.bbsr-geodienste.de/wms/services"
CSW = "https://bbsr-geodienste.de/csw/services"
CATALOGUE_API = "https://gdk.gdi-de.org/geonetwork/srv/api/records/"
CATALOGUE_PAGE = "https://gdk.gdi-de.org/gdi-de/srv/ger/catalog.search#/metadata/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")
# The BBSR hosts ship an incomplete certificate chain, the same reason check_geodb_links.py
# relaxes verification: this is about whether a human reaches content.
CONTEXT = ssl._create_unverified_context()
LEVEL_SUFFIX = re.compile(r"_(kreise|gemeinden|gemeindeverbaende|raumordnungsregionen|bundeslaender)$")
LEVEL_NAMES = {"kreise": "Kreise", "gemeinden": "Gemeinden", "gemeindeverbaende": "Gemeindeverbände",
               "raumordnungsregionen": "Raumordnungsregionen", "bundeslaender": "Bundesländer"}


def get(url: str, timeout: int = 90) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout, context=CONTEXT) as response:
        return response.read().decode("utf-8", "replace")


def wms_layers() -> List[Dict[str, str]]:
    xml = get(f"{WMS}?request=GetCapabilities&service=WMS")
    root = ET.fromstring(xml)
    ns = "{http://www.opengis.net/wms}"
    out: List[Dict[str, str]] = []
    for layer in root.iter(ns + "Layer"):
        name = layer.find(ns + "Name")
        title = layer.find(ns + "Title")
        if name is None or not (name.text or "").strip():
            continue
        found = LEVEL_SUFFIX.search(name.text.strip())
        if not found:  # boundaries, typologies and the group layers, not indicators
            continue
        out.append({"layer": name.text.strip(),
                    "title": (title.text or "").strip() if title is not None else "",
                    "level": LEVEL_NAMES[found.group(1)]})
    return out


def csw_records() -> List[Dict[str, str]]:
    xml = get(f"{CSW}?service=CSW&version=2.0.2&request=GetRecords&typeNames=csw:Record"
              "&resultType=results&elementSetName=brief&maxRecords=500"
              "&outputSchema=http://www.opengis.net/cat/csw/2.0.2")
    out: List[Dict[str, str]] = []
    for record in re.findall(r"<csw:BriefRecord.*?</csw:BriefRecord>", xml, re.S):
        ident = re.search(r"<dc:identifier[^>]*>([^<]+)", record)
        title = re.search(r"<dc:title[^>]*>([^<]+)", record)
        if ident:
            out.append({"id": ident.group(1).strip(),
                        "title": title.group(1).strip() if title else ""})
    return out


def resolves(record: Dict[str, str]) -> bool:
    """Is this record really in the national catalogue? Its title has to come back."""
    try:
        body = get(CATALOGUE_API + record["id"], timeout=45)
    except Exception:
        return False
    probe = record["title"][:14].lower()
    return bool(probe) and probe in body.lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-resolve", action="store_true")
    args = parser.parse_args()

    layers = wms_layers()
    records = csw_records()
    print(f"WMS-Indikatorebenen: {len(layers)} | Katalogeinträge: {len(records)}")

    if args.skip_resolve:
        for record in records:
            record["resolves"] = None
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for record, ok in zip(records, pool.map(resolves, records)):
                record["resolves"] = ok
        print(f"davon im nationalen Geodatenkatalog auflösbar: {sum(bool(r['resolves']) for r in records)}")

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wms": WMS,
        "csw": CSW,
        "catalogue_page": CATALOGUE_PAGE,
        "licence": "Datenlizenz Deutschland Namensnennung (BBSR, Laufende Raumbeobachtung).",
        "layers": layers,
        "records": records,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"geschrieben: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
