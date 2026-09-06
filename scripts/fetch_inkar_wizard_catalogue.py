#!/usr/bin/env python3
"""Join our INKAR records to the identifiers the INKAR application itself uses.

Why this is needed: a link into INKAR has to name the indicator the way the application does, and
the workbook we build our records from uses a different numbering. Two identifiers exist:

  * `M_ID`, which the workbook carries and which is what the application's time selection calls
    `indicator` (verified on 2026-09-06: our M_ID 1101 is the id the wizard writes for
    Arbeitslosenquote);
  * `Gruppe`, the id of the indicator inside the application's own catalogue (12 for the same
    indicator), which the wizard writes into the indicator selection.

Only 11 of 660 records have the same number in both, so the two catalogues are joined by name
within a theme block instead. The blocks line up exactly: our four workbook sheets have 413 / 109 /
89 / 43 rows and the application's areas group into the same four sizes, so the join is unambiguous
for 654 of 660 records. The six that stay behind are the ZOM classification variables (Zentralörtlicher
Status, Stadt-/Gemeindetyp, RegioStaR), which the wizard does not offer as indicators at all.

For each joined indicator this also records the spatial level its link should open on. That comes
from the application (`Wizard/GetRaumbezuege`), not from a guess, and the preference is the level a
reader most likely wants while keeping the stored query small: districts first, then the coarser
levels. Written to data_sources/22-inkar/raw/wizard_katalog.json, read by the permalink service.

Run (about six minutes, one request at a time):
  python scripts/fetch_inkar_wizard_catalogue.py
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
OURS = REPO_ROOT / "soep_metadata_output" / "inkar_metadata_2025.json"
TARGET = REPO_ROOT / "data_sources" / "22-inkar" / "raw" / "wizard_katalog.json"
BASE = "https://www.inkar.de/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")
CONTEXT = ssl._create_unverified_context()
EMPTY_WIZ = ('{§IndicatorCollection§:[],§TimeCollection§:[],§SpaceCollection§:[],'
             '§Title§:§GeoLAB§,§pageorder§:1,§currentpage§:1,§modified§:false}')

# Which level a link opens on. Districts are the level most regional work uses and the one nearly
# every indicator has; the rest are fallbacks for indicators published only coarser or for Europe.
LEVEL_PREFERENCE = ["KRE", "KR", "ROR", "RBZ", "BL", "EUM", "NUTS2", "N2", "WO", "BU"]
# Above this a stored query gets fat (one entry per area), so a level is only used when it fits.
MAX_AREAS = 500

# Workbook sheet -> the application's top-level area, matched by block size (413/109/89/43).
SHEET_OF_AREA = {
    "Zentrale Orte Monitoring": "ZOM",
    "Europa": "Raumbeobachtung EU",
    "SDG-Indikatoren für Kommunen": "SDG",
}


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    for source, target in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss")):
        folded = folded.replace(source, target)
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def call(path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers={
        "User-Agent": UA, "Referer": BASE + "WizardStart",
        "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=120, context=CONTEXT) as response:
        body = response.read().decode("utf-8", "replace")
    value = json.loads(body)
    # The service double-encodes: the body is a JSON string holding the JSON document.
    return json.loads(value) if isinstance(value, str) and value.strip().startswith("{") else value


def wizard_catalogue(pause: float) -> Dict[str, Dict[str, Any]]:
    empty = {"IndicatorCollection": [], "TimeCollection": [], "SpaceCollection": [],
             "Title": "GeoLAB", "pageorder": 1, "currentpage": 1, "modified": False}
    areas = call("Wizard/GetBereiche", empty)["Bereiche"]
    out: Dict[str, Dict[str, Any]] = {}
    for area in areas:
        found = call("Wizard/GetIndikatorenZuBereich",
                     {"bereichsID": area["ID"], "wiz": EMPTY_WIZ})["Indikatoren"]
        for entry in found:
            entry["BereichName"] = f'{area["Bereich"]} / {area["Unterbereich"]}'
            out[str(entry["Gruppe"])] = entry
        time.sleep(pause)
    return out


def levels_for(entry: Dict[str, Any], pause: float) -> List[Dict[str, Any]]:
    selection = {
        "IndicatorCollection": [{k: entry[k] for k in
                                 ("KurznamePlus", "Bereich", "Gruppe", "BU", "EU", "Zeitreihe")}],
        "TimeCollection": [], "SpaceCollection": [],
        "Title": "GeoLAB", "pageorder": 1, "currentpage": 2, "modified": False,
    }
    answer = call("Wizard/GetRaumbezuege", selection)
    time.sleep(pause)
    return answer.get("Raumbezüge") or answer.get("Raumbezuege") or []


def pick_level(levels: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    usable = [lv for lv in levels if int(lv.get("NGeb") or 0) <= MAX_AREAS]
    for wanted in LEVEL_PREFERENCE:
        for level in usable:
            if level.get("ID") == wanted:
                return level
    return min(usable, key=lambda lv: int(lv.get("NGeb") or 0)) if usable else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pause", type=float, default=0.3, help="Sekunden zwischen Anfragen")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    records = json.loads(OURS.read_text(encoding="utf-8"))
    live = wizard_catalogue(args.pause)
    print(f"Katalog der Anwendung: {len(live)} Indikatoren", flush=True)

    index = defaultdict(list)
    for entry in live.values():
        head = entry["BereichName"].split(" / ")[0]
        index[(SHEET_OF_AREA.get(head, "Raumbeobachtung DE"), norm(entry["KurznamePlus"]))].append(entry)

    joined: Dict[str, Dict[str, Any]] = {}
    unmatched: List[str] = []
    todo = records[:args.limit] if args.limit else records
    for record in todo:
        sheet = record.get("sheet", "")
        candidates = (index.get((sheet, norm(record.get("short_name", ""))))
                      or index.get((sheet, norm(record.get("name", "")))))
        if not candidates or len(candidates) > 1:
            unmatched.append(f'{sheet}: {record.get("short_name", "")}')
            continue
        entry = candidates[0]
        level = pick_level(levels_for(entry, args.pause))
        if not level:
            unmatched.append(f'{sheet}: {record.get("short_name", "")} (keine nutzbare Ebene)')
            continue
        years = [y for y in (record.get("available_years") or []) if isinstance(y, int)]
        joined[str(record["m_id"])] = {
            "indicator": {k: entry[k] for k in
                          ("KurznamePlus", "Bereich", "Gruppe", "BU", "EU", "Zeitreihe")},
            "bereich_name": entry["BereichName"],
            "level": level["ID"],
            "level_name": (level.get("Kurzname") or "").strip(),
            "areas": int(level.get("NGeb") or 0),
            "year": str(max(years)) if years else "",
            "short_name": record.get("short_name", ""),
        }
        if len(joined) % 50 == 0:
            print(f"  {len(joined)} zugeordnet", flush=True)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": BASE + "WizardStart",
        "note": ("M_ID ist die Kennung der Zeitauswahl, Gruppe die des Indikatorkatalogs; "
                 "verknüpft über Blatt und Name."),
        "indicators": joined,
        "unmatched": unmatched,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"zugeordnet: {len(joined)} von {len(records)}, ohne Zuordnung: {len(unmatched)}")
    for line in unmatched[:8]:
        print("   ", line)
    print("geschrieben:", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
