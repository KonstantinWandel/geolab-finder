#!/usr/bin/env python3
"""Check every source address in the registry, in a real browser.

Two things rot without anyone noticing. A portal reorganises and an address returns 404, and, the
worse case, a domain lapses and someone else picks it up: `breitband-monitor.de` began redirecting
to a company site, and the finder was still offering it as a portal card. A plain status check
would have called that one healthy, because the redirect answers 200.

So this reports three things per source: the status, the address actually reached after redirects,
and whether that address left the original domain. Chromium is used rather than urllib because
several federal portals refuse scripted requests and would otherwise be reported as dead
(GENESIS-Online and the Deutschlandatlas both do).

    ~/miniconda3/envs/webshot/bin/python scripts/check_source_urls.py
    ~/miniconda3/envs/webshot/bin/python scripts/check_source_urls.py --json-out output/source_urls.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "data_sources" / "registry" / "geo_sources.json"


def registered_urls() -> list[dict]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [{"slug": s["slug"], "name": s["name"], "url": s["url"]}
            for s in data["sources"] if s.get("url")]


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


async def check_all(entries: list[dict], timeout_ms: int) -> list[dict]:
    from playwright.async_api import async_playwright

    out: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(ignore_https_errors=True)
        for entry in entries:
            page = await context.new_page()
            record = dict(entry, status=None, final_url="", moved=False, error="")
            try:
                response = await page.goto(entry["url"], wait_until="domcontentloaded",
                                           timeout=timeout_ms)
                record["status"] = response.status if response else None
                record["final_url"] = page.url
                record["moved"] = domain(page.url) != domain(entry["url"])
                record["title"] = (await page.title())[:80]
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {str(exc)[:70]}"
            await page.close()
            out.append(record)
        await browser.close()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json-out", default="")
    # 40 s was too short: the Hochschulkompass answers, but takes 46 s, and a checker
    # that cries wolf is a checker nobody reads.
    parser.add_argument("--timeout", type=int, default=75000)
    args = parser.parse_args()

    entries = registered_urls()
    results = asyncio.run(check_all(entries, args.timeout))

    broken = [r for r in results if r["error"] or (r["status"] or 0) >= 400]
    moved = [r for r in results if r["moved"] and not r["error"]]
    print(f"{len(results)} Quelladressen geprüft am {date.today().isoformat()}\n")
    if broken:
        print("NICHT ERREICHBAR:")
        for r in broken:
            print(f"  {r['slug']:<44} {r['error'] or 'http ' + str(r['status'])}")
    if moved:
        print("\nLEITET AUF EINE ANDERE DOMAIN (prüfen, wer dort jetzt sitzt):")
        for r in moved:
            print(f"  {r['slug']:<44} {domain(r['url'])} -> {domain(r['final_url'])}")
            print(f"      {r.get('title', '')}")
    if not broken and not moved:
        print("alle Adressen antworten und bleiben auf ihrer eigenen Domain")

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked": date.today().isoformat(), "results": results},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\ngeschrieben: {path}")


if __name__ == "__main__":
    main()
