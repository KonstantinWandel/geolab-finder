#!/usr/bin/env python3
"""How usable are the links of the results the finder puts on top?

The retrieval gates ask whether the right record is found. They say nothing about whether its link
opens the numbers or a search mask, and that is what a user actually runs into: a colleague's first
test of "Krankenhäuser" got a statistic information page at rank 1 while the record that opens the
table sat at rank 6.

This measures the link level of the top hits over the gate's own queries, so a ranking change can
be judged on both axes at once. Run it before and after such a change.

    GEOLAB_APP_MODE=inkar ... python scripts/eval_link_precision.py
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.soep_rag_advisor import SOEPRagAdvisorService  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from eval_geodb_search import CASES  # noqa: E402

ORDER = ["indicator", "table", "statistic", "dataset", "portal"]
# "usable" = the link opens the thing itself, without a second search
USABLE = {"indicator", "table"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=3, help="how many top hits to look at per query")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    service = SOEPRagAdvisorService()
    service.load()

    at1: collections.Counter = collections.Counter()
    intop: collections.Counter = collections.Counter()
    usable_first = 0
    for query, _pattern, _sources in CASES:
        rows = service.answer_research_question(query, top_k=args.top)["recommended_variables"]
        if not rows:
            continue
        at1[rows[0].get("link_level") or "none"] += 1
        if any((r.get("link_level") or "") in USABLE for r in rows):
            usable_first += 1
        for row in rows:
            intop[row.get("link_level") or "none"] += 1

    total = sum(at1.values())
    print(f"{total} Anfragen\n")
    print("Verlinkungstiefe des ersten Treffers:")
    for level in ORDER + ["none"]:
        if at1[level]:
            share = 100 * at1[level] / total
            print(f"  {level:<11} {at1[level]:>3}  {share:5.1f}%")
    print(f"\ndirekt nutzbarer Link (Indikator oder Tabelle) auf Platz 1: "
          f"{at1['indicator'] + at1['table']}/{total}")
    print(f"irgendwo in den ersten {args.top}: {usable_first}/{total}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"queries": total, "top1": dict(at1), f"top{args.top}": dict(intop),
             "usable_at_1": at1["indicator"] + at1["table"], "usable_in_top": usable_first},
            ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
