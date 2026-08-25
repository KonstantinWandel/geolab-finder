#!/usr/bin/env python3
"""Resolve the regional level of every Zensus 2022 table.

In Zensus 2022 the regional level is encoded in the opaque table code, not in the title, so
1,284 of 1,440 table records had no spatial level and were invisible to the spatial filter.
`metadata/table` returns the table structure, whose GEO* variables name the level, and
`catalogue/variables?selection=GEO*` gives the authoritative list of those variables.

Writes data_sources/29-zensus-2022/raw/zensus_table_levels.json:
  {"<table code>": {"geo": [["GEOLK4", "Landkreise u. krsfr. Städte", 400], ...]}, ...}

Resumable: an existing output file is loaded first and only missing codes are fetched, so a
killed run continues where it stopped. Run detached, it takes hours for 1,440 tables:
  setsid python scripts/resolve_zensus_levels.py </dev/null >logs/zensus_levels.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "data_sources" / "29-zensus-2022" / "raw"
CATALOGUE = SOURCE_DIR / "genesis_catalogue_zensus.json"
OUT_PATH = SOURCE_DIR / "zensus_table_levels.json"
SECRET = Path.home() / "kwandel" / ".config" / "secrets" / "zensus_token.txt"
BASE = "https://ergebnisse.zensus2022.de/api/rest/2020/"


def token() -> str:
    match = re.search(r"key\s*=\s*(\S+)", SECRET.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"No `key=` line in {SECRET}")
    return match.group(1)


def call(tok: str, path: str, timeout: int = 120, **params: str) -> Dict[str, Any]:
    data = urllib.parse.urlencode({"language": "de", **params}).encode()
    request = urllib.request.Request(
        BASE + path, data=data,
        headers={"username": tok, "password": "", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sleep", type=float, default=0.4)
    args = parser.parse_args()

    tok = token()
    login = call(tok, "helloworld/logincheck", timeout=60)
    if str(login.get("Username", "")).upper() in {"GAST", ""}:
        raise SystemExit("Authenticated as GAST: the token was not accepted.")
    print("[auth] ok (not GAST)", flush=True)

    geo_vars = {
        entry["Code"]: (entry.get("Content", ""), entry.get("Values"))
        for entry in (call(tok, "catalogue/variables", selection="GEO*", pagelength="200").get("List") or [])
    }
    print(f"[geo] {len(geo_vars)} GEO variables known", flush=True)

    codes = [str(t["Code"]).strip() for t in json.loads(CATALOGUE.read_text(encoding="utf-8"))["tables"]]
    resolved: Dict[str, Any] = {}
    if OUT_PATH.exists():
        resolved = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        print(f"[resume] {len(resolved)} already resolved", flush=True)

    todo = [c for c in codes if c not in resolved]
    print(f"[start] {len(todo)} of {len(codes)} tables to resolve", flush=True)
    for position, code in enumerate(todo, start=1):
        try:
            structure = (call(tok, "metadata/table", name=code).get("Object") or {}).get("Structure") or {}
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            print(f"[warn] {code}: {type(exc).__name__} {exc}", flush=True)
            time.sleep(5)
            continue
        found: List[List[Any]] = []
        for block in ("Columns", "Rows"):
            for entry in structure.get(block) or []:
                entry_code = str(entry.get("Code") or "")
                if entry_code.startswith("GEO"):
                    label, values = geo_vars.get(entry_code, (entry.get("Content", ""), entry.get("Values")))
                    found.append([entry_code, label, values])
        resolved[code] = {"geo": found}
        if position % 50 == 0:
            OUT_PATH.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[progress] {position}/{len(todo)}, {sum(1 for v in resolved.values() if v['geo'])} with a level",
                  flush=True)
        time.sleep(args.sleep)

    OUT_PATH.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tables": len(resolved),
                      "with_level": sum(1 for v in resolved.values() if v["geo"]),
                      "path": str(OUT_PATH)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
