#!/usr/bin/env python3
"""Resolve GENESIS Merkmal codes to the statistic that carries them, so they can be deep-linked.

Why this exists: 1,596 of the 3,305 Regionalstatistik records (15% of the whole GeoDB index)
linked only to the portal home page, because their statistic code could not be mined out of the
Destatis definition text. The portal is a JSF app that cannot be deep-linked by Merkmal, but
`/genesis/online/statistic/<code>` opens the statistic, and `catalogue/statistics2variable`
returns exactly that code for a Merkmal. One call per Merkmal turns a home-page link into a
"this statistic contains it" link.

Resumable and safe to re-run: the output file is loaded first and only unresolved codes are
requested, so a killed run costs the codes it had not reached yet. Codes that genuinely resolve
to nothing are recorded as an empty list, not retried forever; the Datenguide catalogue is a
2020 snapshot and some Merkmale no longer exist in either live instance.

    setsid python scripts/resolve_merkmal_statistics.py </dev/null >logs/merkmal_resolve.log 2>&1 &
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
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS = Path.home() / "kwandel" / ".config" / "secrets"
KEYS_DIR = REPO_ROOT / "data_sources" / "21-datenguide-abgeschaltet" / "raw" / "genesapi-data" / "keys"
OUT_PATH = REPO_ROOT / "data_sources" / "21-datenguide-abgeschaltet" / "raw" / "merkmal_statistics.json"
ALIVE = REPO_ROOT / "logs" / "merkmal_resolve_alive.json"

# The regional instance is asked first: these are Regionaldatenbank Merkmale, and a regional
# statistic link is the useful one for this finder. The federal instance is the fallback for
# Merkmale the regional database does not carry.
INSTANCES = [
    ("regionalstatistik", "https://www.regionalstatistik.de/genesisws/rest/2020/", "regionalstatistik.txt"),
    ("destatis", "https://genesis.destatis.de/genesisWS/rest/2020/", "destatis_key.txt"),
]


def read_token(filename: str) -> str:
    text = (SECRETS / filename).read_text(encoding="utf-8")
    match = re.search(r"key\s*=\s*(\S+)", text)
    if not match:
        raise SystemExit(f"No `key=` line in {SECRETS / filename}")
    return match.group(1)


def call(base: str, token: str, path: str, timeout: int = 180, **params: str) -> Dict[str, Any]:
    data = urllib.parse.urlencode({"language": "de", **params}).encode()
    request = urllib.request.Request(
        base + path, data=data,
        headers={"username": token, "password": "",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


METADATA = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"


def merkmal_codes() -> List[str]:
    """The Merkmale that still need a link.

    Preferably exactly the records that currently point at the portal home page, read from the
    built metadata: looking up the ones that already carry a statistic link would be 1,100
    pointless requests against a service that caps parallelism. Falls back to the whole
    Datenguide key catalogue when no metadata has been built yet. The key files are named
    `<CODE>_de.json` / `<CODE>_en.json`, so the language suffix has to come off.
    """
    if METADATA.exists():
        records = json.loads(METADATA.read_text(encoding="utf-8"))
        codes = sorted({
            str(record.get("variable_name", "")).strip()
            for record in records
            if record.get("source_key") == "regionalstatistik"
            and record.get("link_level") == "portal"
            and str(record.get("variable_name", "")).strip()
        })
        if codes:
            return codes
    if not KEYS_DIR.exists():
        raise SystemExit(f"missing {KEYS_DIR}; run scripts/fetch_sources.py first")
    return sorted({re.sub(r"_(de|en)$", "", path.stem) for path in KEYS_DIR.glob("*.json")})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sleep", type=float, default=0.8)
    parser.add_argument("--limit", type=int, default=0, help="stop after N new lookups (for a smoke test)")
    args = parser.parse_args()

    tokens = {}
    for name, base, secret in INSTANCES:
        token = read_token(secret)
        login = call(base, token, "helloworld/logincheck", timeout=60)
        username = str(login.get("Username", ""))
        if not username or username.upper() == "GAST":
            raise SystemExit(f"{name}: authenticated as GAST, refusing to write a catalogue")
        tokens[name] = token
        print(f"[auth] {name} ok", flush=True)

    resolved: Dict[str, Any] = {}
    if OUT_PATH.exists():
        resolved = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("merkmale") or {}
        print(f"[resume] {len(resolved)} codes already resolved", flush=True)

    codes = [code for code in merkmal_codes() if code not in resolved]
    print(f"[plan] {len(codes)} codes to look up", flush=True)

    def save() -> None:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps({
            "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "merkmale": resolved,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    for position, code in enumerate(codes, start=1):
        entry: Dict[str, Any] = {"statistics": [], "instance": None}
        for name, base, _secret in INSTANCES:
            try:
                found = call(base, tokens[name], "catalogue/statistics2variable",
                             name=code, pagelength="50").get("List") or []
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
                print(f"[warn] {code} on {name}: {type(exc).__name__} {exc}", flush=True)
                time.sleep(5)
                continue
            if found:
                entry = {
                    "instance": name,
                    "statistics": [{"code": str(item.get("Code", "")).strip(),
                                    "label": item.get("Content", "")} for item in found],
                }
                break
            time.sleep(args.sleep)
        resolved[code] = entry
        if position % 25 == 0:
            hit = sum(1 for value in resolved.values() if value.get("statistics"))
            print(f"[progress] {position}/{len(codes)} looked up, {hit} of {len(resolved)} resolved",
                  flush=True)
            save()
            ALIVE.parent.mkdir(parents=True, exist_ok=True)
            ALIVE.write_text(json.dumps({
                "last_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "done": position, "of": len(codes), "resolved": hit,
            }), encoding="utf-8")
        if args.limit and position >= args.limit:
            break
        time.sleep(args.sleep)

    save()
    hit = sum(1 for value in resolved.values() if value.get("statistics"))
    print(json.dumps({"codes": len(resolved), "resolved": hit, "output": str(OUT_PATH)}, indent=2))


if __name__ == "__main__":
    main()
