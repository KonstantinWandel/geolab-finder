#!/usr/bin/env python3
"""Review sampled client-rendered links without treating their HTML shells as success."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path


async def run(args):
    from playwright.async_api import async_playwright

    metadata = json.loads(args.metadata.read_text())
    rows = {r.get("indicator_url") or r.get("source_url"): r for r in metadata}
    health = json.loads(args.health.read_text())
    samples = {r["url"]: r for r in health["results"] if r["verdict"] == "shell" or "unreachable" in r["verdict"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results, screenshots = [], set()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="de-DE", ignore_https_errors=True)
        for url, sample in samples.items():
            row = rows[url]
            page = await context.new_page()
            result = {"source": row["source_key"], "url": url, "code": row["variable_name"], "label": row["label"], "error": ""}
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
                result["status"] = response.status if response else None
                for _ in range(15):
                    await page.wait_for_timeout(1000)
                    body = await page.locator("body").inner_text()
                    result["code_visible"] = row["variable_name"].lower() in body.lower()
                    result["label_visible"] = row["label"].lower().replace(" (iör-monitor)", "") in body.lower()
                    if result["code_visible"] or result["label_visible"]:
                        break
                result["indicator_header"] = await page.locator("#indikator_header_rechts, .indikator_header").first.inner_text() if await page.locator("#indikator_header_rechts, .indikator_header").count() else ""
                result["title"] = await page.title()
                result["body_excerpt"] = body[:350]
                result["final_url"] = page.url
                if row["source_key"] not in screenshots or "unreachable" in sample["verdict"]:
                    target = args.output.parent / f"browser-{row['source_key']}-{len(results)}.png"
                    await page.screenshot(path=str(target))
                    result["screenshot"] = str(target)
                    screenshots.add(row["source_key"])
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
            finally:
                await page.close()
            results.append(result)
            print(result["source"], result["code"], "code visible:", result.get("code_visible"), "label visible:", result.get("label_visible"), result["error"], flush=True)
            args.output.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(),
                "scope": "Sampled browser evidence only; absent visible text is inconclusive, not a confirmed dead link. No login or tracking-consent bypass.",
                "results": results, "complete": len(results) == len(samples)}, ensure_ascii=False, indent=2) + "\n")
        await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
