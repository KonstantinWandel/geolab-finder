#!/usr/bin/env python3
"""Verify the IÖR-Monitor deep links by opening them in a browser.

`check_geodb_links.py` cannot judge these: monitor.ioer.de is a Leaflet application whose HTML
shell is the same 4.7 KB for every query string, valid indicator or not, so HTTP status and body
size say nothing about whether the link works. What does say it is the map header the app writes
once it has loaded the indicator named in `?ind=`. This script reads that header and compares it
with the label of the record the link came from.

Needs playwright, so it runs in the same env as `check_source_urls.py`:

  ~/miniconda3/envs/webshot/bin/python scripts/check_ioer_links.py
  ~/miniconda3/envs/webshot/bin/python scripts/check_ioer_links.py --limit 12 --json-out out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"
HEADER = "#indikator_header_rechts, .indikator_header"


def records(limit: int) -> List[Dict[str, str]]:
    data = json.loads(METADATA.read_text(encoding="utf-8"))
    rows = [{"code": r["variable_name"], "url": r["indicator_url"],
             "label": r["label"].replace(" (IÖR-Monitor)", "")}
            for r in data if r.get("source_key") == "ioer_monitor" and r.get("indicator_url")]
    return rows[:limit] if limit else rows


def words(text: str) -> set:
    # Five letters and up, so that "der"/"und"/"an" cannot make two different indicators match.
    return {w for w in re.findall(r"\w{5,}", text.lower())}


async def check(browser, row: Dict[str, str], patience: int) -> Dict[str, Any]:
    page = await browser.new_page()
    header = ""
    try:
        await page.goto(row["url"], wait_until="domcontentloaded", timeout=120_000)
        for _ in range(patience):
            await page.wait_for_timeout(2000)
            header = await page.evaluate(
                "sel => { const el = document.querySelector(sel); return el ? el.innerText.trim() : ''; }",
                HEADER)
            if header:
                break
    except Exception as exc:  # a timeout is a result here, not a crash
        header = f"FEHLER: {exc}"
    finally:
        await page.close()
    rendered = bool(header) and not header.startswith("FEHLER")
    return {**row, "header": header, "rendered": rendered,
            "matches": bool(words(row["label"]) & words(header))}


async def run(rows: List[Dict[str, str]], workers: int, patience: int) -> List[Dict[str, Any]]:
    from playwright.async_api import async_playwright
    results: List[Dict[str, Any]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 1100, "height": 760}, locale="de-DE")
        queue = asyncio.Queue()
        for row in rows:
            queue.put_nowait(row)

        async def worker() -> None:
            while not queue.empty():
                row = await queue.get()
                result = await check(context, row, patience)
                results.append(result)
                state = "ok  " if result["matches"] else ("LEER" if not result["rendered"] else "?   ")
                print(f"  {state} {result['code']:6s} {result['header'].splitlines()[0][:66] if result['header'] else ''}",
                      flush=True)
                queue.task_done()

        await asyncio.gather(*[worker() for _ in range(workers)])
        await browser.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="check only the first N links")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--patience", type=int, default=20, help="2-second waits for the map header")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    rows = records(args.limit)
    print(f"IÖR-Tiefenlinks: {len(rows)}")
    results = asyncio.run(run(rows, args.workers, args.patience))
    rendered = sum(r["rendered"] for r in results)
    matched = sum(r["matches"] for r in results)
    print(f"\n{rendered}/{len(results)} öffnen einen Indikator, {matched} nennen den erwarteten Namen")
    for r in sorted(results, key=lambda x: x["code"]):
        if not r["matches"]:
            print(f"  PRUEFEN {r['code']}  {r['url']}\n          erwartet {r['label']!r}, Karte zeigt {r['header']!r}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    # A link that renders nothing is the failure; a name that reads differently is for a human.
    return 1 if rendered < len(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
