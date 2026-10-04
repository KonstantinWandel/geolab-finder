#!/usr/bin/env python3
"""Compare full SOEP ranked identities and scores before/after shared GeoDB changes."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

from eval_soep_search import CASES, matches
from app.services.soep_rag_advisor import SOEPRagAdvisorService


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-service", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("baseline_soep_advisor", args.baseline_service)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = module.SOEPRagAdvisorService()
    after = SOEPRagAdvisorService()
    before.load()
    after.load()
    results = []
    for query, pattern, label in CASES:
        old = before.answer_research_question(query, 10, {"include_raw": False})["recommended_variables"]
        new = after.answer_research_question(query, 10, {"include_raw": False})["recommended_variables"]
        equal = [(r["item_id"], r["score"]) for r in old] == [(r["item_id"], r["score"]) for r in new]
        results.append({"query": query, "identities_and_scores_equal": equal,
                        "rank": next((i + 1 for i, r in enumerate(new) if matches(r, pattern, label)), None)})
        print(query, equal, flush=True)
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "passed": all(r["identities_and_scores_equal"] for r in results),
              "queries": len(results), "metadata_sha256": sha(after.metadata_path),
              "baseline_service_sha256": sha(args.baseline_service),
              "candidate_service_sha256": sha(Path(__file__).resolve().parents[1] / "backend/app/services/soep_rag_advisor.py"),
              "embedding_model": after.model_name, "reranker": after._reranker_name, "results": results}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not report["passed"]:
        raise ValueError("Shared changes altered SOEP ranking")


if __name__ == "__main__":
    main()
