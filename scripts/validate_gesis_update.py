#!/usr/bin/env python3
"""Broad regression gates plus source-grounding and diverse GESIS retrieval checks."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlparse

from build_gesis_metadata import literals
from harvest_gesis import DDI, KG, SCHEMA
from prepare_gesis_index import ROOT, digest
from deploy_gesis_index import gate

CASES = [
    ("Bundesland des Wohnorts", r"bundesland|bundesl[aä]nd|state of residence", "geography"),
    ("administrative district identification code", r"kreis|district|region|gemeinde", "geography"),
    ("town size of respondent place of residence", r"ortsgr|ortsgro|town size|gemeindegr|wohnort", "geography"),
    ("Postleitzahl des Wohnorts", r"postleitzahl|postal|postcode|\bplz\b", "geography"),
    ("Wahlkreisnummer in einer deutschen Wahlstudie", r"wahlkreis|constituenc|electoral district", "geography"),
    ("SOLIKRIS macro data NUTS1", r"solikris", "aggregate"),
    ("regional election aggregates Germany 1976 1980", r"aggregatdaten.*wahlkreis|election results", "aggregate"),
    ("Reichstagswahlen zwischen 1890 und 1912", r"reichstag|wilhelmin", "historical"),
    ("georeferenced radical right support Europe SCoRE", r"score|sub-national context.*radical", "study"),
    ("ZA0950", r"^ZA0950$", "code"),
]


def accepts(row, pattern, kind):
    value = row["variable_name"] if kind == "code" else row["label"] + " " + row["dataset_label"] + " " + row.get("aliases", "")
    if not re.search(pattern, value, re.I):
        return False
    if kind == "geography":
        return row["item_type"] in {"survey_geography_variable", "regional_dataset_variable"}
    if kind == "aggregate":
        return row["item_type"] in {"regional_dataset", "regional_dataset_variable"}
    if kind == "historical":
        return bool(row["historical_geography"])
    return True


def audit(rows):
    db = sqlite3.connect(f"file:{ROOT / 'data_sources/gesis/catalogue.sqlite'}?mode=ro", uri=True)
    count = 0
    for row in rows:
        if row["source_key"] != "gesis":
            continue
        count += 1
        if not row["metadata_only"] or row["map_ready"] or row["observation_data_available"]:
            raise ValueError("GESIS metadata has acquired an observation/plot-ready claim")
        if row["metadata_license"] not in {"CC0-1.0", "CC-BY-4.0"} or not row["metadata_attribution"]:
            raise ValueError("Missing metadata attribution")
        if urlparse(row["indicator_url"]).hostname not in {"search.gesis.org", "dbkapps.gesis.org", "data.gesis.org"}:
            raise ValueError("Unexpected GESIS destination")
        if row["item_type"].endswith("variable"):
            iri = row["metadata_resource_uri"]
            raw = db.execute("SELECT payload FROM documents WHERE kind='kg_variable' AND id=?", (iri,)).fetchone()
            if raw is None:
                raise ValueError("Invented variable identity")
            fields = json.loads(raw[0])
            names = literals(fields, DDI + "variableName") or [iri.rsplit("/", 1)[-1]]
            labels = literals(fields, KG + "variableLabel") or literals(fields, SCHEMA + "name") or names
            if row["variable_name"] not in names or row["label"] not in labels:
                raise ValueError("Variable code/label not grounded in provider RDF")
    db.close()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--qa-dir", type=Path, required=True)
    args = parser.parse_args()
    metadata_path = args.candidate.resolve() / "geodb_metadata.json"
    indexed = json.loads(metadata_path.read_text())
    checked = audit(indexed)
    env = {**os.environ, "GEOLAB_APP_MODE": "inkar", "SOEP_RAG_DEVICE": "cpu",
           "SOEP_METADATA_ROOT": str(args.candidate.resolve()), "INKAR_METADATA_ROOT": str(args.candidate.resolve()),
           "SOEP_RAG_CACHE_DIR": str(args.candidate.resolve() / "cache"),
           "SOEP_EMBEDDING_MODEL": "intfloat/multilingual-e5-large-instruct", "SOEP_EMBEDDING_MAX_SEQ_LENGTH": "512",
           "SOEP_RAG_RERANKER_MODEL": "Alibaba-NLP/gte-multilingual-reranker-base",
           "SOEP_RAG_RERANK_ONNX": str(ROOT / "models/gte-multilingual-reranker-base-onnx-int8"),
           "SOEP_RAG_RERANK_CANDIDATES": "12", "SOEP_RAG_RERANK_DOC_CHARS": "480", "SOEP_RAG_WEAK_MATCH_BELOW": "0.48",
           "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "8"}
    results = {}
    for name, script in (("smoke", "eval_geodb_search.py"), ("hard", "eval_geodb_hard.py")):
        target = args.qa_dir / f"candidate-{name}.json"
        with target.with_suffix(".log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--json-out", str(target)],
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        before = json.loads((args.qa_dir / f"baseline-{name}.json").read_text())
        after = json.loads(target.read_text())
        gate(before, after)
        results[name] = {"before": before["summary"], "after": after["summary"]}
        print(f"Passed {name} regression gate", flush=True)
    os.environ.update(env)
    from app.services.soep_rag_advisor import SOEPRagAdvisorService
    service = SOEPRagAdvisorService()
    service.load()
    cases = []
    for question, pattern, kind in CASES:
        response = service.answer_research_question(question, 10, {"dataset_scope": "gesis"})
        rows = response["recommended_variables"]
        if not rows or any(r["source_key"] != "gesis" for r in rows):
            raise ValueError("Source filter failed")
        rank = next((i + 1 for i, row in enumerate(rows) if accepts(row, pattern, kind)), None)
        cases.append({"query": question, "kind": kind, "rank": rank,
                      "top": [{"id": r["item_id"], "label": r["label"], "type": r["item_type"]} for r in rows[:3]],
                      "weak_match": response["weak_match"]})
        print(f"GESIS {kind}: rank={rank}: {question}", flush=True)
    filtered = service.answer_research_question("regional macro data", 10, {"dataset_scope": "gesis", "nuts_level": "NUTS1"})["recommended_variables"]
    if not filtered or any("NUTS1" not in r["nuts_levels"] for r in filtered):
        raise ValueError("Explicit NUTS filter failed")
    source = next(s for s in service.get_filter_options()["sources"] if s["value"] == "gesis")
    source_checks = []
    for key in sorted({r["source_key"] for r in service._rows}):
        eligible = sorted((r for r in service._rows if r["source_key"] == key and r["item_type"] != "portal"),
                          key=lambda r: r["item_id"])
        if not eligible:
            eligible = [r for r in service._rows if r["source_key"] == key]
        example = eligible[len(eligible) // 2]
        query = example["variable_name"] if re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[\w.-]{4,}", example["variable_name"]) else example["label"]
        response = service.answer_research_question(query, 5, {"dataset_scope": key})
        found = response["recommended_variables"]
        if not found or any(r["source_key"] != key for r in found):
            raise ValueError("Source-scope retrieval contract failed: " + key)
        source_checks.append({"source": key, "query": query, "rows": len(found), "source_filter_passed": True,
                              "top_id": found[0]["item_id"], "top_label": found[0]["label"]})
    contract = {"passed": True, "scope": "One deterministic metadata lookup per provider, checking nonempty results and no source-filter leakage; not an independent semantic-quality benchmark.",
                "sources": source_checks, "records_by_source": dict(Counter(r["source_key"] for r in service._rows))}
    (args.qa_dir / "all-source-contracts.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n")
    retrieval = {"passed": all(c["rank"] for c in cases), "cases": cases, "nuts_filter_passed": True, "source_facet": source}
    (args.qa_dir / "gesis-retrieval.json").write_text(json.dumps(retrieval, ensure_ascii=False, indent=2) + "\n")
    result = {"tested_at": datetime.now(timezone.utc).isoformat(), "passed": retrieval["passed"],
              "metadata_sha256": digest(metadata_path), "source_grounded_rows_checked": checked,
              "service_sha256": digest(ROOT / "backend/app/services/soep_rag_advisor.py"),
              "production_model": service.model_name, "production_reranker": service._reranker_name,
              "candidate_policy": "GeoDB: global dense head plus one best candidate per other provider, at most twice the fixed pool; exact alphanumeric code injection. SOEP unchanged.",
              "configured_global_pool": 12, "rerank_doc_chars": 480,
              "regression_gates": results, "gesis": retrieval,
              "all_source_contracts": contract,
              "report_files_sha256": {p.name: digest(p) for p in args.qa_dir.glob("*.json") if p.is_file()}}
    (ROOT / "data_sources/gesis/QA_REPORT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if not result["passed"]:
        raise ValueError("GESIS retrieval misses; inspect reports before deployment")


if __name__ == "__main__":
    main()
