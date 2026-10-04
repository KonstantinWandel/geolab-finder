#!/usr/bin/env python3
"""Exercise GESIS filtering, selected-row exports and layout in a build or live UI."""
import argparse
import asyncio
import csv
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit


async def check(args, url):
    from playwright.async_api import async_playwright

    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for name, width, height, locale in [("desktop", 1440, 1000, "en-GB"),
                                                 ("mobile", 390, 844, "de-DE")]:
                context = await browser.new_context(viewport={"width": width, "height": height},
                                                    locale=locale, accept_downloads=True)
                page = await context.new_page()
                errors, requests = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url))
                if args.build:
                    async def proxy(route):
                        target = urlsplit(route.request.url)
                        response = await route.fetch(url=args.api.rstrip("/") + target.path +
                                                     ("?" + target.query if target.query else ""))
                        await route.fulfill(response=response)
                    await page.route("**/api/**", proxy)
                await page.goto(url, wait_until="networkidle", timeout=60000)
                if name == "mobile":
                    await page.get_by_role("combobox", name="Language", exact=True).select_option("de")
                await page.get_by_role("button", name="Decline all" if name == "desktop" else "Alles ablehnen", exact=True).click()
                source = page.locator(".facet").filter(has=page.locator(".facet-label", has_text="Search source" if name == "desktop" else "Datenquelle"))
                await source.locator(".facet-trigger").click()
                await source.locator(".facet-item").filter(has_text="GESIS").get_by_role("checkbox").check()
                await source.locator(".facet-done").click()
                await page.locator(".chat-input").fill("residential federal state of survey respondents")
                async with page.expect_response(lambda r: r.url.endswith("/api/soep/advice") and r.request.method == "POST", timeout=180000) as event:
                    await page.locator(".btn-primary[type=submit]").click()
                response = await event.value
                assert response.ok, f"Search returned {response.status}"
                payload = await response.json()
                rows = payload["recommended_variables"]
                assert rows and all(r["source_key"] == "gesis" for r in rows)
                assert all(r["metadata_only"] and not r["map_ready"] for r in rows)
                await page.locator(".result-select").first.check()
                expected = rows[0]
                files = {}
                for format in ("CSV", "JSON"):
                    async with page.expect_download() as event:
                        await page.get_by_role("button", name=format, exact=True).click()
                    download = await event.value
                    path = args.output.parent / f"{name}-selected.{format.lower()}"
                    await download.save_as(path)
                    if format == "CSV":
                        with path.open(encoding="utf-8-sig", newline="") as handle:
                            exported = list(csv.DictReader(handle))
                    else:
                        exported = json.loads(path.read_text())
                    assert len(exported) == 1
                    record = exported[0]
                    for key in ("metadata_license", "metadata_attribution", "metadata_resource_uri", "study_id", "data_access"):
                        assert record[key] == expected.get(key, ""), (key, record[key], expected.get(key))
                    assert str(record["metadata_only"]).lower() == "true"
                    assert str(record["map_ready"]).lower() == "false"
                    files[format] = str(path)
                assert await page.locator("a.mini-chip", has_text="Metadata:" if name == "desktop" else "Metadaten:").count()
                await page.locator(".result-item").first.scroll_into_view_if_needed()
                await page.screenshot(path=str(args.output.parent / f"gesis-ui-{name}.png"))
                layout = await page.evaluate("({width: innerWidth, content: document.documentElement.scrollWidth})")
                assert layout["content"] <= width, layout
                assert not errors, errors
                assert not any("/analytics" in u or "/quality" in u or "/feedback" in u for u in requests)
                results.append({"viewport": name, "locale": locale, "results": len(rows),
                                "selected_exports": files, "no_horizontal_overflow": True,
                                "javascript_errors": errors, "quality_or_analytics_requests": 0})
                await context.close()
        finally:
            await browser.close()
    args.output.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(),
        "url": url, "api": args.api if args.build else url, "passed": True,
        "build_index_sha256": hashlib.sha256((args.build / "index.html").read_bytes()).hexdigest() if args.build else None,
        "checks": results}, indent=2) + "\n")
    print(args.output.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--url", default="https://geodb.geolab.soz.uni-bielefeld.de/")
    parser.add_argument("--api", default="https://geodb.geolab.soz.uni-bielefeld.de")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    server = None
    try:
        if args.build:
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(args.build.resolve())))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            args.url = f"http://127.0.0.1:{server.server_port}/"
        asyncio.run(check(args, args.url))
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
