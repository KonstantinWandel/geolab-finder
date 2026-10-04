#!/usr/bin/env python3
"""Download the provider's public KG metadata export, not archived survey data.

The official landing page marks this specific export as CC-BY-4.0 and accessible
without registration. Its own download controls are used normally; no challenge
or access restriction is bypassed. Run in the existing webshot environment.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
LANDING = "https://data.gesis.org/sharing/#!Detail/10.7802/2969"
FILES = ["GESISKG_readme_v2-0-0_.txt", "GESISKG_resources_researchdata_v2-0-0.zip",
         "GESISKG_resources_variable_links_v2-0-0.zip", "GESISKG_resources_variables_v2-0-0.zip"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "data_sources/gesis")
    args = parser.parse_args()
    destination = args.folder / "raw/bulk"
    destination.mkdir(parents=True, exist_ok=True)
    manifest_file = args.folder / "BULK_DOWNLOAD_REPORT.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {
        "landing": LANDING, "doi": "10.7802/2969", "version": "2.0.0", "license": "CC-BY-4.0", "files": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.route("**/*google*", lambda r: r.abort())
        page.route("**/*etracker*", lambda r: r.abort())
        page.goto(LANDING, wait_until="domcontentloaded", timeout=60000)
        expect(page.get_by_text(FILES[0], exact=True)).to_be_visible(timeout=60000)
        body = page.locator("body").inner_text()
        if "Freier Zugang (ohne Registrierung)" not in body or "CC BY 4.0" not in body:
            raise ValueError("Export access or licence changed; stop before accepting/download")
        page.locator("label").filter(has_text="Ich stimme").click()
        for filename in FILES:
            target = destination / filename
            if target.exists() and filename in manifest["files"]:
                if hashlib.sha256(target.read_bytes()).hexdigest() == manifest["files"][filename]["sha256"]:
                    print("Verified cached " + filename, flush=True)
                    continue
                raise ValueError("Cached bulk download checksum changed")
            name = page.get_by_text(filename, exact=True)
            details = name.evaluate('''e => {
              const root = e.closest('.v-button') || e;
              let previous = root.previousElementSibling;
              while (previous && previous.getAttribute('role') !== 'combobox') previous = previous.previousElementSibling;
              let next = root.nextElementSibling, detail = '';
              while (next && next.getAttribute('role') !== 'combobox') { detail += next.textContent; next = next.nextElementSibling; }
              return {inputId: previous?.querySelector('input')?.id, detail};
            }''')
            match = re.search(r"MD5:\s*(?:MD5:)?([a-f0-9]{32})", details["detail"], re.I)
            if not details["inputId"] or not match:
                raise ValueError("Provider file/purpose/checksum markup changed")
            page.locator("#" + details["inputId"]).locator("..").locator(".v-filterselect-button").click()
            page.get_by_text("Für wissenschaftliche Forschung (inkl. Promotion)", exact=True).click()
            with page.expect_download(timeout=180000) as event:
                page.get_by_role("button", name=filename, exact=True).click()
            download = event.value
            if download.suggested_filename != filename:
                raise ValueError("Unexpected provider download filename")
            part = target.with_suffix(target.suffix + ".part")
            download.save_as(part)
            raw = part.read_bytes()
            if hashlib.md5(raw).hexdigest() != match.group(1).lower():
                raise ValueError("Provider-published MD5 does not match the file")
            part.replace(target)
            manifest["files"][filename] = {"fetched_at": datetime.now(timezone.utc).isoformat(),
                                            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                            "provider_md5": match.group(1).lower()}
            manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")
            print("Downloaded and verified " + filename, flush=True)
        browser.close()


if __name__ == "__main__":
    main()
