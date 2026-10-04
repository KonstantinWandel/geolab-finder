#!/usr/bin/env python3
"""Record dense candidate crowding and production reranker scores for a query."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.soep_rag_advisor import SOEPRagAdvisorService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queries", nargs="+")
    parser.add_argument("--source", default="all")
    parser.add_argument("--depth", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    service = SOEPRagAdvisorService()
    service.load()
    reports = []
    for query in args.queries:
        candidates = service._search(query, args.depth, {"dataset_scope": args.source})
        pairs = []
        for row in candidates:
            head = f"{row.get('variable_name', '')} - {row.get('label', '')}. {row.get('theme', '')}. "
            tail = f". {row.get('available_years_text', '')}. {', '.join(row.get('spatial_levels') or [])}"
            body = row.get("search_description") or row.get("rich_description", "")
            pairs.append((query, head + body[:max(0, service._rerank_doc_chars - len(head) - len(tail))] + tail))
        scores = service._get_reranker().predict(pairs)
        rows = [{"dense_rank": i + 1, "dense_score": row["score"], "rerank_score": float(scores[i]),
                 "source": row["source_key"], "dataset": row["dataset_label"], "type": row["item_type"],
                 "code": row["variable_name"], "label": row["label"], "rerank_doc": pairs[i][1]}
                for i, row in enumerate(candidates)]
        reports.append({"query": query, "head_sources": dict(Counter(r["source"] for r in rows[:12])), "rows": rows})
        print(query, reports[-1]["head_sources"], flush=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
