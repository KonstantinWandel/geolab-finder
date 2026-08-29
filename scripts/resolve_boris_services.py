#!/usr/bin/env python3
"""Find the Bodenrichtwerte service (WMS/WFS) each Bundesland publishes, via the GDI-DE catalogue.

BORIS-D is a viewer over sixteen Laender services and publishes no catalogue of its own, so its
sixteen per-Land records could only link to the BORIS-D home page. The official German metadata
catalogue (Geodatenkatalog.de) does hold those services: a CSW summary search finds the records,
and `GetRecordById` with the full ISO profile carries the actual GetCapabilities URL.

Two steps, both cheap:
  1. page through every `AnyText like '%bodenrichtwert%'` summary (about 2,000)
  2. for each Bundesland pick the best candidate and read its service URL out of the full record

A candidate is preferred when it is a service rather than a dataset, when the Land name is in the
title rather than only in the keywords, and when the title has no Kreis or city name in it, so a
Land-wide service wins over one district's 2023 layer.

Output: data_sources/33-boris-d-bodenrichtwerte/raw/boris_services.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data_sources" / "33-boris-d-bodenrichtwerte" / "raw" / "boris_services.json"
CSW = "https://gdk.gdi-de.org/gdi-de/srv/eng/csw"
UA = "geolab-geodb-indexer/1.0 (+https://geodb.geolab.soz.uni-bielefeld.de)"

STATES = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen",
    "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz",
    "Saarland", "Sachsen-Anhalt", "Sachsen", "Schleswig-Holstein", "Thüringen",
]
# Only abbreviations that are unambiguous as whole words. The first attempt allowed two-letter
# codes ("bb", "sh", "sn", "he") and matching on keywords instead of the title, which mapped
# Berlin to Brandenburg's WMS, Schleswig-Holstein to a Stuttgart city service and Hessen to a
# development plan in Treuenbrietzen. A wrong service link is worse than the portal link it
# replaces, so an ambiguous Land is left unresolved instead.
STATE_ALIASES = {
    "Baden-Württemberg": ["baden-wuerttemberg", "lgl bw"],
    "Bayern": ["bayerische", "bayerisches"],
    "Berlin": [],
    "Brandenburg": [],
    "Bremen": ["bremerhaven"],
    "Hamburg": [],
    "Hessen": ["hessische", "hessisches"],
    "Mecklenburg-Vorpommern": ["mv"],
    "Niedersachsen": ["boris.ni", "boris ni"],
    "Nordrhein-Westfalen": ["nrw", "boris-nrw"],
    "Rheinland-Pfalz": ["rlp"],
    "Saarland": ["brw-sl"],
    "Sachsen-Anhalt": ["lsa"],
    "Sachsen": [],
    "Schleswig-Holstein": [],
    "Thüringen": ["thueringen"],
}
# A district or city in the title means the record covers that district, not the Land.
LOCAL_HINT = re.compile(r"\b(kreis|landkreis|stadt|gemeinde|verbandsgemeinde|region\s|amt\s)\b", re.I)


def fold(value: str) -> str:
    """Casefold and normalise umlauts so "Thüringen" and "Thueringen" compare equal."""
    text = (value or "").casefold()
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(source, target)
    return text


def fetch(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def summaries(term: str, cap: int = 2500, sleep: float = 0.3) -> List[Dict[str, Any]]:
    """Every CSW summary record matching the term."""
    constraint = urllib.parse.quote(f"AnyText like '%{term}%'")
    found: List[Dict[str, Any]] = []
    matched = 0
    for start in range(1, cap, 100):
        url = (f"{CSW}?service=CSW&version=2.0.2&request=GetRecords&typeNames=csw:Record"
               f"&resultType=results&elementSetName=summary&constraintLanguage=CQL_TEXT"
               f"&constraint_language_version=1.1.0"
               f"&outputSchema={urllib.parse.quote('http://www.opengis.net/cat/csw/2.0.2', safe='')}"
               f"&constraint={constraint}&startPosition={start}&maxRecords=100")
        body = fetch(url)
        if not matched:
            hit = re.search(r'numberOfRecordsMatched="(\d+)"', body)
            matched = int(hit.group(1)) if hit else 0
            print(f"[csw] {matched} records match '{term}'", flush=True)
        chunk = re.findall(r"<csw:SummaryRecord[ >].*?</csw:SummaryRecord>", body, re.S)
        if not chunk:
            break
        for record in chunk:
            title = re.search(r"<dc:title>([^<]*)</dc:title>", record)
            identifier = re.search(r"<dc:identifier>([^<]*)</dc:identifier>", record)
            kind = re.search(r"<dc:type>([^<]*)</dc:type>", record)
            found.append({
                "id": unescape(identifier.group(1)) if identifier else "",
                "title": unescape(title.group(1)).strip() if title else "",
                "type": (kind.group(1) if kind else "").strip(),
                "subjects": [unescape(s) for s in re.findall(r"<dc:subject>([^<]*)</dc:subject>", record)],
            })
        if len(found) >= matched:
            break
        time.sleep(sleep)
    return found


def service_url(identifier: str, state: str = "") -> Optional[Dict[str, str]]:
    """The GetCapabilities (or other online resource) URL from a record's full ISO metadata."""
    url = (f"{CSW}?service=CSW&version=2.0.2&request=GetRecordById&id={urllib.parse.quote(identifier)}"
           f"&elementSetName=full"
           f"&outputSchema={urllib.parse.quote('http://www.isotc211.org/2005/gmd', safe='')}")
    try:
        body = fetch(url)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"[warn] {identifier}: {type(exc).__name__} {exc}", flush=True)
        return None
    links = [unescape(u) for u in re.findall(r"<gmd:URL>([^<]+)</gmd:URL>", body)]
    capabilities = [u for u in links if "getcapabilities" in u.lower()]
    portal = [u for u in links if u.lower().startswith("http") and "getcapabilities" not in u.lower()]
    organisation = re.search(r"<gmd:organisationName>.*?<gco:CharacterString>([^<]*)<", body, re.S)
    if not capabilities and not portal:
        return None

    def prefer(urls: List[str]) -> str:
        """A joint record (Niedersachsen und Bremen) carries one URL per Land."""
        if state:
            hints = [fold(state).replace("-", ""), fold(state).split("-")[0]]
            hints += [fold(alias).replace(" ", "") for alias in STATE_ALIASES.get(state, [])]
            for url in urls:
                host = fold(urllib.parse.urlparse(url).netloc).replace("-", "")
                if any(hint and hint in host for hint in hints):
                    return url
        return urls[0] if urls else ""

    return {
        "capabilities": prefer(capabilities),
        "portal": prefer(portal),
        "organisation": unescape(organisation.group(1)).strip() if organisation else "",
    }


def score(record: Dict[str, Any], state: str) -> int:
    """How likely this record is the Land-wide Bodenrichtwerte service.

    Everything is judged on the TITLE: the keyword lists in these records are wide enough that a
    Land name in them says nothing about coverage.
    """
    title = fold(record["title"])
    # "BORIS" is the name every Land gives this system, and Hessen's service is titled exactly
    # "BORIS Hessen" with no occurrence of the word Bodenrichtwert.
    if "bodenrichtwert" not in title and not re.search(r"\bboris\b", title):
        return -1
    words = set(re.split(r"[^a-z0-9.\-]+", title))
    own = fold(state)
    aliases = [fold(alias) for alias in STATE_ALIASES[state]]
    # Whole-word only: "sachsen" is a substring of "sachsen-anhalt", and matching it as a
    # substring handed Sachsen the Sachsen-Anhalt WMS.
    own_word = re.search(rf"(?<![a-z]){re.escape(own)}(?![a-z-])", title) is not None
    matched = own_word or any(
        alias in words or (" " in alias and alias in title) for alias in aliases)
    if not matched:
        return -1
    # A different Bundesland named in the title disqualifies the record, but only as a whole
    # word, only when it is not part of this Land's own name ("sachsen" sits inside both
    # "niedersachsen" and "sachsen-anhalt"), and only when this Land is NOT also named:
    # Niedersachsen and Bremen run one joint system, "BORIS.NI - Bodenrichtwert-
    # informationssystem Niedersachsen und Bremen", which belongs to both.
    own_named = own_word
    for other in STATES:
        if other == state or fold(other) in fold(state):
            continue
        if re.search(rf"(?<![a-z]){re.escape(fold(other))}", title) and not own_named:
            return -1
    value = 40
    if "bodenrichtwert" in title:                      # over a record that only says BORIS
        value += 30
    if record["type"] == "service" or re.match(r"^(wms|wfs|oaf|ogc)\b", title):
        value += 30
    if LOCAL_HINT.search(record["title"]) or re.search(r"(?<![a-z])(lk|sk)(?![a-z])", title):
        value -= 40                                    # one district's layer, not the Land's
    if "immobilienrichtwert" in title:                 # the neighbouring product
        value -= 20
    if "basisdienst" in title:                         # RLP: Land-wide, vs the per-Kreis premium
        value += 15
    if "premiumdienst" in title:
        value -= 15
    if re.search(r"\b(19|20)\d{2}\b", record["title"]):   # a single vintage is narrower
        value -= 15
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", default="bodenrichtwert")
    parser.add_argument("--candidates", type=int, default=5,
                        help="full records to try per Bundesland before giving up")
    args = parser.parse_args()

    records = summaries(args.term)
    print(f"[csw] harvested {len(records)} summaries", flush=True)

    services: Dict[str, Any] = {}
    for state in STATES:
        ranked = sorted(
            ((score(record, state), record) for record in records),
            key=lambda pair: -pair[0],
        )
        ranked = [record for value, record in ranked if value > 0][: args.candidates]
        chosen = None
        for record in ranked:
            resolved = service_url(record["id"], state)
            time.sleep(0.4)
            if resolved and (resolved["capabilities"] or resolved["portal"]):
                chosen = {"title": record["title"], "id": record["id"],
                          "type": record["type"], **resolved}
                break
        services[state] = chosen
        print(f"[{state}] " + (f"{chosen['title'][:52]} -> "
                               f"{(chosen['capabilities'] or chosen['portal'])[:70]}"
                               if chosen else "no service record found"), flush=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "catalogue": CSW,
        "term": args.term,
        "records_matched": len(records),
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "states": services,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    hit = sum(1 for value in services.values() if value)
    print(json.dumps({"states_resolved": hit, "of": len(STATES), "output": str(OUT_PATH)}, indent=2))


if __name__ == "__main__":
    main()
