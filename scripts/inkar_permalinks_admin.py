#!/usr/bin/env python3
"""Look after the INKAR deep links: what we created, whether it still works, and how to undo it.

The finder links INKAR indicators through `/api/inkar/open/<M_ID>`, which creates one stored query
on the BBSR server the first time an indicator is opened (see
backend/app/services/inkar_permalink.py). That leaves rows in someone else's system, so there has
to be a way to see them, check them and take them back, and it has to be one command.

  --list      what we have created, oldest first
  --check     do a sample of them still resolve? (they are the only thing our links depend on)
  --delete-all  remove every query we created and empty the local cache

The cache lives next to the served metadata; on the VM that is
/opt/geolab/app/destatis-rag/soep_metadata_output/inkar_permalinks.json, so this normally runs
there, or with --cache pointing at a copy.
"""
from __future__ import annotations

import argparse
import json
import random
import ssl
import urllib.request
from pathlib import Path
from typing import Any, Dict

BASE = "https://www.inkar.de/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")
CONTEXT = ssl._create_unverified_context()
DEFAULT_CACHE = "/opt/geolab/app/destatis-rag/soep_metadata_output/inkar_permalinks.json"


def call(path: str, payload: Dict[str, Any] | None = None) -> str:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers={
        "User-Agent": UA, "Referer": BASE, "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=60, context=CONTEXT) as response:
        return response.read().decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", type=int, default=0, metavar="N", help="N Stichproben prüfen")
    parser.add_argument("--delete-all", action="store_true")
    args = parser.parse_args()

    path = Path(args.cache)
    if not path.exists():
        print(f"keine Ablage unter {path} (noch nichts angelegt)")
        return 0
    cache = json.loads(path.read_text(encoding="utf-8"))
    links = cache.get("links") or {}
    print(f"angelegte Abfragen: {len(links)} | Nutzerkennung vorhanden: {bool(cache.get('user'))}")

    if args.list:
        for m_id, entry in sorted(links.items(), key=lambda kv: kv[1].get("created", "")):
            print(f"  {entry.get('created','?')}  M_ID {m_id:>6}  {entry.get('level',''):4}  "
                  f"{entry.get('title','')[:40]:42} {BASE}#{entry['id']}")

    if args.check:
        sample = random.sample(list(links.items()), min(args.check, len(links)))
        gut = 0
        for m_id, entry in sample:
            try:
                body = call(f"Main/GetUserQuery/{entry['id']}")
                ok = "IndicatorCollection" in body
            except Exception as fehler:  # noqa: BLE001
                ok = False
                body = str(fehler)
            gut += ok
            print(f"  {'ok  ' if ok else 'WEG '} M_ID {m_id:>6} {entry.get('title','')[:36]}")
        print(f"{gut} von {len(sample)} Abfragen sind noch da"
              + ("" if gut == len(sample) else "; der Dienst legt fehlende beim nächsten Klick neu an"))
        return 0 if gut == len(sample) else 1

    if args.delete_all:
        user = cache.get("user")
        if not user:
            print("keine Nutzerkennung, nichts zu löschen")
            return 0
        weg = 0
        for m_id, entry in list(links.items()):
            try:
                call("Main/DeleteQuery/", {"user": user, "id": entry["id"]})
                weg += 1
            except Exception as fehler:  # noqa: BLE001
                print(f"  M_ID {m_id}: {fehler}")
        cache["links"] = {}
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{weg} Abfragen beim BBSR gelöscht, Ablage geleert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
