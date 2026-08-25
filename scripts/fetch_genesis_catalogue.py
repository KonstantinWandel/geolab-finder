#!/usr/bin/env python3
"""Enumerate a GENESIS-Online instance's catalogue (statistics + tables) over the REST API.

Two instances matter here:
  regionalstatistik  www.regionalstatistik.de  (the Regionaldatenbank: Kreis/Gemeinde depth)
  destatis           genesis.destatis.de       (the federal database)

**Auth gotcha, verified 2026-08-25:** the token goes in the HTTP header as `username` with an
empty `password`, on a POST. `Authorization: Bearer <token>` also returns HTTP 200 from
`helloworld/logincheck`, but with `"Username":"GAST"` (guest) and then 401 on every catalogue
call. A 200 is not proof of auth: check that `Username` is not GAST before trusting a run.

Tokens live in ~/kwandel/.config/secrets/ as `key=<token>`; this script reads them and never
prints them.

Output: data_sources/<the instance's own folder>/raw/genesis_catalogue_<instance>.json
        {"instance", "fetched_at", "statistics": [...], "tables": [...]}

Run detached; a full table enumeration takes minutes:
  setsid python scripts/fetch_genesis_catalogue.py --instance regionalstatistik \
      </dev/null >logs/genesis_regio.log 2>&1 &
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
# Each instance is its own row in the workbook, so its catalogue lands in its own folder.
OUT_DIRS = {
    "regionalstatistik": REPO_ROOT / "data_sources" / "21-datenguide-abgeschaltet" / "raw",
    "destatis": REPO_ROOT / "data_sources" / "28-genesis-online-bund" / "raw",
    "zensus": REPO_ROOT / "data_sources" / "29-zensus-2022" / "raw",
}
SECRETS = Path.home() / "kwandel" / ".config" / "secrets"

INSTANCES = {
    "regionalstatistik": {
        "base": "https://www.regionalstatistik.de/genesisws/rest/2020/",
        "secret": "regionalstatistik.txt",
        "portal": "https://www.regionalstatistik.de/genesis/online",
    },
    "destatis": {
        "base": "https://genesis.destatis.de/genesisWS/rest/2020/",
        "secret": "destatis_key.txt",
        "portal": "https://www-genesis.destatis.de/genesis/online",
    },
    "zensus": {
        "base": "https://ergebnisse.zensus2022.de/api/rest/2020/",
        "secret": "zensus_token.txt",
        "portal": "https://ergebnisse.zensus2022.de/datenbank/online",
    },
}

# Instances are separate hosts with separate tokens and separate rate limits, so crawling
# them concurrently is safe. Concurrency WITHIN one instance is not: the service caps
# parallel requests (Destatis says 3, Regionalstatistik 10) and starts killing long-running
# ones. One process per instance, sequential inside it.


def read_token(filename: str) -> str:
    text = (SECRETS / filename).read_text(encoding="utf-8")
    match = re.search(r"key\s*=\s*(\S+)", text)
    if not match:
        raise SystemExit(f"No `key=` line in {SECRETS / filename}")
    return match.group(1)


def call(base: str, token: str, path: str, timeout: int = 300, **params: str) -> Dict[str, Any]:
    data = urllib.parse.urlencode({"language": "de", **params}).encode()
    request = urllib.request.Request(
        base + path, data=data,
        headers={"username": token, "password": "", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", choices=sorted(INSTANCES), default="regionalstatistik")
    parser.add_argument("--pagelength", default="2500")
    parser.add_argument("--sleep", type=float, default=1.0, help="pause between calls; the service caps parallel requests")
    args = parser.parse_args()

    config = INSTANCES[args.instance]
    token = read_token(config["secret"])

    login = call(config["base"], token, "helloworld/logincheck", timeout=60)
    username = str(login.get("Username", ""))
    if username.upper() == "GAST" or not username:
        raise SystemExit("Authenticated as GAST (guest): the token was not accepted. "
                         "Check that it belongs to this instance and is sent as the `username` header.")
    print(f"[auth] ok on {args.instance} (username is not GAST)", flush=True)

    statistics = call(config["base"], token, "catalogue/statistics",
                      selection="*", pagelength=args.pagelength).get("List") or []
    print(f"[statistics] {len(statistics)}", flush=True)

    tables: List[Dict[str, Any]] = []
    seen: set = set()
    for position, statistic in enumerate(statistics, start=1):
        code = str(statistic.get("Code", "")).strip()
        if not code:
            continue
        try:
            # A statistic with no tables returns "List": null, not an empty list.
            found = call(config["base"], token, "catalogue/tables",
                         selection=f"{code}*", pagelength=args.pagelength).get("List") or []
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            print(f"[warn] {code}: {type(exc).__name__} {exc}", flush=True)
            time.sleep(5)
            continue
        for table in found:
            table_code = str(table.get("Code", "")).strip()
            if table_code and table_code not in seen:
                seen.add(table_code)
                table["StatistikCode"] = code
                table["StatistikContent"] = statistic.get("Content", "")
                tables.append(table)
        if position % 25 == 0:
            print(f"[tables] {position}/{len(statistics)} statistics, {len(tables)} tables", flush=True)
        time.sleep(args.sleep)

    out_dir = OUT_DIRS[args.instance]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"genesis_catalogue_{args.instance}.json"
    out_path.write_text(json.dumps({
        "instance": args.instance,
        "portal": config["portal"],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statistics": statistics,
        "tables": tables,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"instance": args.instance, "statistics": len(statistics),
                      "tables": len(tables), "path": str(out_path)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
