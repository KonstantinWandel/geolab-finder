#!/usr/bin/env python3
"""Measure whether the outward links in geodb_metadata.json actually resolve.

The link is the product, so its health is a number we should hold ourselves to rather than
an assumption. For each source_key a sample of records is fetched and classified:

  ok            HTTP 2xx and the body is bigger than that host's known "not found" page
  shell         HTTP 2xx but the body matches the size of a deliberately bogus code, i.e.
                the portal is a client-rendered SPA and the link cannot be verified here
  http-<code>   the server answered 4xx/5xx
  unreachable   DNS/TLS/timeout

Bogus-code probes: for a host whose deep links carry a code, the same URL with an invalid
code is fetched once, and its byte length becomes that host's shell signature. That is what
separates "the table opened" from "the portal home page opened".

Run:
  python scripts/check_geodb_links.py --per-source 8
  python scripts/check_geodb_links.py --per-source 3 --json-out output/link_health.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
import http.cookiejar
import ssl
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")

# url pattern -> a URL of the same shape with a deliberately invalid code
BOGUS_PROBES = {
    "regionalstatistik.de/genesis/online?operation=table":
        "https://www.regionalstatistik.de/genesis/online?operation=table&code=99999-99-99-9",
    "www-genesis.destatis.de/genesis/online?operation=table":
        "https://www-genesis.destatis.de/genesis/online?operation=table&code=99999-9999",
    "ergebnisse.zensus2022.de/datenbank/online/table":
        "https://ergebnisse.zensus2022.de/datenbank/online/table/9999X-9999",
    "regionalatlas.statistikportal.de/?BL=DE":
        "https://regionalatlas.statistikportal.de/?BL=DE&TCode=ZZZZ&ICode=ZZ9999",
    "regionalstatistik.de/genesis/online/statistic":
        "https://www.regionalstatistik.de/genesis/online/statistic/99999",
}


def fetch_size(url: str, timeout: int = 45) -> Any:
    # www-genesis.destatis.de times out on a bare urllib request but answers curl in
    # milliseconds, so send the same header set a browser would.
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Connection": "close",
    })
    try:
        # inkar.de and a few federal hosts ship an incomplete chain; this check is about
        # whether a human reaches content, not about certificate hygiene.
        context = ssl._create_unverified_context()
        # deutschlandatlas.bund.de answers 307 to a cookie-check URL and only serves the page
        # to a client that keeps the cookie. Without a jar the response looks like a hard
        # failure, which is why this host was wrongly recorded as unreachable by any script.
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            urllib.request.HTTPSHandler(context=context),
        )
        with opener.open(request, timeout=timeout) as response:
            return len(response.read())
    except urllib.error.HTTPError as exc:
        return f"http-{exc.code}"
    except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
        # www-genesis.destatis.de times out on urllib but answers curl in milliseconds, so
        # a failure here is retried with curl before being reported as unreachable.
        import shutil
        import subprocess
        curl = shutil.which("curl")
        if curl:
            try:
                done = subprocess.run(
                    [curl, "-sk", "-L", "--max-time", str(timeout), "-A", UA,
                     "-o", "/dev/null", "-w", "%{http_code} %{size_download}", url],
                    capture_output=True, text=True, timeout=timeout + 10)
                status, _, size = done.stdout.strip().partition(" ")
                if status.startswith("2"):
                    return int(size)
                if status and status != "000":
                    return f"http-{status}"
            except (subprocess.SubprocessError, OSError, ValueError):
                pass
        return f"unreachable ({str(getattr(exc, 'reason', exc))[:40]})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-source", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    records = json.loads(METADATA.read_text(encoding="utf-8"))
    by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_source[record["source_key"]].append(record)

    rng = random.Random(args.seed)
    sample: List[Dict[str, Any]] = []
    for source, rows in sorted(by_source.items()):
        sample.extend(rng.sample(rows, min(args.per_source, len(rows))))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        shells = dict(zip(BOGUS_PROBES, pool.map(fetch_size, BOGUS_PROBES.values())))
    print("shell signatures (bytes returned for a deliberately invalid code):")
    for key, size in shells.items():
        print(f"  {size!s:>10}  {key}")

    urls = [row.get("indicator_url") or row.get("source_url") for row in sample]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        sizes = list(pool.map(fetch_size, urls))

    results: List[Dict[str, Any]] = []
    for row, url, size in zip(sample, urls, sizes):
        verdict = "ok"
        if isinstance(size, str):
            verdict = size
        else:
            for key, shell in shells.items():
                if key in (url or "") and isinstance(shell, int) and abs(size - shell) < max(64, shell * 0.02):
                    verdict = "shell"
                    break
        results.append({"source_key": row["source_key"], "link_level": row.get("link_level"),
                        "url": url, "bytes": size, "verdict": verdict})

    print("\nper source (sampled):")
    per_source: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in results:
        per_source[item["source_key"]][item["verdict"].split(" ")[0]] += 1
    for source in sorted(per_source):
        counts = ", ".join(f"{verdict} {count}" for verdict, count in sorted(per_source[source].items()))
        print(f"  {source:<26} {counts}")

    bad = [r for r in results if r["verdict"] != "ok"]
    print(f"\n{len(results) - len(bad)}/{len(results)} sampled links resolved to content.")
    for item in bad:
        print(f"  {item['verdict']:<22} [{item['source_key']}] {item['url'][:90]}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"shells": {k: str(v) for k, v in shells.items()},
                                   "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
