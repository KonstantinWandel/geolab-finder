"""Find out which GENESIS Merkmale exist in the Regionaldatenbank, so their record can link to
the Merkmal page instead of to the statistic that contains it.

`resolve_merkmal_statistics.py` says the portal "cannot be deep-linked by Merkmal". That is true
for `?operation=merkmal`, which lands on the home page, and false for `?operation=variable&code=`,
which opens the Merkmal with its Ausprägungen and its tabs for tables and statistics.

**Asked through the API, not by fetching the page.** Two earlier versions of this script decided
existence by fetching the HTML page and looking at it, and both produced wrong answers that looked
entirely normal:

  * six parallel fetches made the portal answer with another code's page (it keeps the current
    selection in server-side state), inflating 2,439 codes to 2,268 hits;
  * fetching sequentially but treating "the empty-result phrase is absent" as proof of a page
    counted every error and session page as a hit, and after about 1,700 requests the portal
    started returning such pages, so the truth anchors below failed at the end of that run.

`catalogue/variables?selection=<CODE>` answers the same question with a documented interface, a
token, and no load on the public UI. A Merkmal exists here when the catalogue returns that exact
code. Checked against ten codes verified by hand in a browser: all ten agree.

Resumable: the output is loaded first and only unknown codes are requested.

    setsid python scripts/resolve_merkmal_pages.py </dev/null >logs/merkmal_pages.log 2>&1 &
"""
from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
METADATA = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"
OUT_PATH = REPO_ROOT / "data_sources" / "21-datenguide-abgeschaltet" / "raw" / "merkmal_pages.json"
BASE = "https://www.regionalstatistik.de/genesis/online?operation=variable&code="
API = "https://www.regionalstatistik.de/genesisws/rest/2020/"
SECRETS = Path.home() / "kwandel" / ".config" / "secrets"


def read_token() -> str:
    text = (SECRETS / "regionalstatistik.txt").read_text(encoding="utf-8")
    match = re.search(r"key\s*=\s*(\S+)", text)
    if not match:
        raise SystemExit("kein `key=` in regionalstatistik.txt")
    return match.group(1)


TOKEN = read_token()
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")
CONTEXT = ssl._create_unverified_context()


def merkmal_codes() -> List[str]:
    rows = json.loads(METADATA.read_text(encoding="utf-8"))
    return sorted({row["variable_name"] for row in rows
                   if row.get("source_key") == "regionalstatistik"
                   and str(row.get("item_id", "")).startswith("genesis:")
                   and row.get("dataset_label") == "Merkmal"})


def api_call(path: str, **params: str) -> Dict[str, Any]:
    data = urllib.parse.urlencode({"language": "de", **params}).encode()
    request = urllib.request.Request(API + path, data=data, headers={
        "username": TOKEN, "password": "", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=120, context=CONTEXT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def lookup(code: str) -> Tuple[bool, str]:
    """Does the Regionaldatenbank carry this Merkmal, and what does it call it today?

    The catalogue has to name the exact code; a near match ("selection" is a prefix search) is a
    different Merkmal. The live wording is kept because the Datenguide catalogue these codes come
    from is a 2020 snapshot and has drifted: of 624 codes, 116 read differently today and a few
    differ in substance ("Lebendgeborene je 10.000 Einwohner" is "je 1.000 EW" now, and BEV012 is
    no longer Wanderungssaldo but Sterbefälle je 1 000 Einwohner).
    """
    for attempt in range(3):
        try:
            found = api_call("catalogue/variables", selection=code, pagelength="10")
            for entry in found.get("List") or []:
                if str(entry.get("Code", "")).upper() == code.upper():
                    return True, str(entry.get("Content") or "").strip()
            return False, ""
        except Exception:
            time.sleep(2 + 3 * attempt)
    return False, ""


def probe(code: str) -> bool:
    return lookup(code)[0]


# Ten codes checked by hand in a browser on 2026-09-05, five with a page and five without. They
# are probed before and after every run: if the rule or the service drifts, this says so instead
# of letting a plausible-looking result set through, which is what happened twice here.
TRUTH = {"ABWAT3": True, "BAUAT2": True, "STEU08": True, "KIND01": True, "BEV003": True,
         "GUT011": False, "UNT026": False, "EKM008": False, "NW-KRE": False, "WZ03X9": False}


def check_truth(label: str) -> bool:
    wrong = [code for code, expected in TRUTH.items() if probe(code) != expected]
    print(f"Wahrheitsanker {label}: {len(TRUTH) - len(wrong)}/{len(TRUTH)} richtig"
          + (f", falsch: {', '.join(wrong)}" if wrong else ""), flush=True)
    return not wrong


def main() -> int:
    parser = argparse.ArgumentParser()
    # The catalogue query carries the code in the request and keeps no session state, so a few
    # parallel calls are safe here in a way that fetching the portal page never was. The service
    # itself asks for at most ten at a time.
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recheck-positives", action="store_true",
                        help="re-probe the codes already recorded as having a page")
    args = parser.parse_args()

    known: Dict[str, bool] = {}
    labels: Dict[str, str] = {}
    if OUT_PATH.exists():
        stored = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        known = stored.get("merkmale") or {}
        labels = stored.get("labels") or {}
    if args.recheck_positives:
        codes = [c for c, has in known.items() if has]
        print(f"Nachprüfung von {len(codes)} früheren Positiven mit der strengeren Regel", flush=True)
    else:
        codes = [c for c in merkmal_codes() if c not in known]
    if args.limit:
        codes = codes[:args.limit]
    print(f"Merkmale gesamt: {len(merkmal_codes())}, noch zu prüfen: {len(codes)}", flush=True)

    if args.workers > 10:
        print("WARNUNG: der Dienst drosselt ab zehn gleichzeitigen Anfragen", flush=True)
    if not check_truth("vor dem Lauf"):
        print("Abbruch: der Test misst nicht, was er messen soll", flush=True)
        return 2

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for code, (has_page, content) in zip(codes, pool.map(lookup, codes)):
            known[code] = has_page
            if content:
                labels[code] = content
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(codes)}, mit eigener Seite: {sum(known.values())}", flush=True)
                OUT_PATH.write_text(json.dumps(
                    {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "url_pattern": BASE + "<code>", "merkmale": known, "labels": labels},
                    ensure_ascii=False, indent=1), encoding="utf-8")

    OUT_PATH.write_text(json.dumps(
        {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "url_pattern": BASE + "<code>", "merkmale": known, "labels": labels},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"fertig: {sum(known.values())} von {len(known)} Merkmalen haben eine eigene Seite")

    ok = check_truth("nach dem Lauf")
    # Re-probe a sample of the positives as well. On its own this proved too weak (it re-ran the
    # same flawed rule and passed), which is why the anchors above exist.
    positives = [code for code, has_page in known.items() if has_page]
    sample = positives[:: max(1, len(positives) // 20)][:20]
    wrong = [code for code in sample if not probe(code)]
    print(f"Nachprüfung von {len(sample)} Positiven: {len(wrong)} falsch"
          + (f" ({', '.join(wrong)})" if wrong else ""))
    return 0 if ok and not wrong else 1


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used in probe)
    raise SystemExit(main())
