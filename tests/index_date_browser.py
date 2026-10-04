"""Verify the built/live GeoDB date note without searches or visitor telemetry."""
import argparse
from contextlib import contextmanager
from datetime import datetime
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TIMESTAMP = "2026-10-04T18:58:38.625994+00:00"
OPTIONS = {"sources": [{"value": "inkar", "label": "INKAR"}], "datasets": [],
           "themes": [], "spatial_levels": [], "nuts_levels": [], "sample_groups": [],
           "year_min": 1330, "year_max": 2070, "index_built": TIMESTAMP}


@contextmanager
def serve(directory):
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def check(url, output, live=False):
    screenshots, checks, errors = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        timestamp = TIMESTAMP
        if live:
            response = p.request.new_context().get(url.rstrip("/") + "/api/soep/filter-options")
            assert response.ok
            timestamp = response.json()["index_built"]
        date = datetime.fromisoformat(timestamp).astimezone(ZoneInfo("Europe/Berlin"))
        expected = {"de": "Index vom " + date.strftime("%d.%m.%Y"),
                    "en": "Index as of " + f"{date.day} {date.strftime('%B %Y')}"}
        for width, height in [(1440, 960), (390, 844)]:
            context = browser.new_context(viewport={"width": width, "height": height}, locale="en-GB")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def api(route):
                path = route.request.url
                if not live and "/soep/filter-options" in path:
                    route.fulfill(json=OPTIONS)
                elif "/soep/facet-counts" in path:
                    route.fulfill(json={})
                elif live and "/soep/filter-options" in path:
                    route.continue_()
                else:
                    raise AssertionError(f"Unexpected API request: {path}")

            page.route("**/api/**", api)
            page.goto(url, wait_until="networkidle", timeout=60000)
            note = page.locator(".filter-note")
            expect(note).to_have_text(expected["en"])
            page.get_by_role("button", name="Decline all", exact=True).click()
            for language in ["de", "en"]:
                page.locator("select[aria-label='Language'], select[aria-label='Sprache']").select_option(language)
                expect(note).to_have_text(expected[language])
                expect(note).to_be_visible()
                assert "|" not in note.inner_text() and "T18" not in note.inner_text()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                path = output.parent / f"index-date-{'live' if live else 'build'}-{language}-{width}.png"
                page.screenshot(path=str(path), full_page=True)
                screenshots.append(str(path))
                checks.append({"width": width, "language": language, "text": note.inner_text()})
            if not live:
                # Unusable metadata must not expose a raw timestamp or an invalid-date string.
                for value in [None, "not-a-date"]:
                    page.unroute("**/api/**")
                    page.route("**/api/**", lambda route: route.fulfill(json={**OPTIONS, "index_built": value})
                               if "/filter-options" in route.request.url else route.fulfill(json={}))
                    page.reload(wait_until="networkidle")
                    expect(note).to_have_count(0)
            assert not context.cookies()
            context.close()
        assert not errors, errors
        browser.close()
    return {"passed": True, "url": url, "checks": checks, "screenshots": screenshots, "javascript_errors": errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=ROOT / "frontend/dist-inkar")
    parser.add_argument("--url")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.url:
        report = check(args.url, args.output, live=True)
    else:
        with serve(args.build.resolve()) as url:
            report = check(url, args.output)
        report["build_index_sha256"] = hashlib.sha256((args.build / "index.html").read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
