#!/usr/bin/env python3
"""Append a verified GESIS snapshot without refetching or rewriting existing sources."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.soep_rag_advisor import SOEPRagAdvisorService


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gesis", type=Path, default=ROOT / "data_sources/gesis")
    args = parser.parse_args()
    from_file = args.gesis / "geodb_records.json"
    report = json.loads((args.gesis / "REGIONAL_REPORT.json").read_text())
    if not report.get("harvest_complete") or report["records_sha256"] != digest(from_file):
        raise ValueError("Complete and checksum-verified GESIS metadata required")
    additions = json.loads(from_file.read_text())
    if len(additions) != report["indexed_records"] or any(r["source_key"] != "gesis" for r in additions):
        raise ValueError("GESIS record count/source mismatch")
    base_path = args.baseline / "geodb_metadata.json"
    existing = json.loads(base_path.read_text())
    if any(r.get("source_key") == "gesis" for r in existing):
        raise ValueError("This append workflow requires a baseline without GESIS; rebase explicitly for a later refresh")
    vectors_path = args.baseline / "geodb_metadata_embeddings.npy"
    vectors = np.load(vectors_path)
    stamp = json.loads(vectors_path.with_suffix(".npy.meta.json").read_text())
    service = SOEPRagAdvisorService()
    if stamp["model"] != service.model_name or stamp["max_seq_length"] != service.embedding_max_seq_length:
        raise ValueError("Baseline embedding model/context does not match the production service")
    if vectors.shape != (len(existing), stamp["dim"]):
        raise ValueError("Baseline metadata/vector mismatch")
    rows = existing + additions
    existing_ids = Counter(r["item_id"] for r in existing)
    added_ids = [r["item_id"] for r in additions]
    if len(set(added_ids)) != len(added_ids) or set(added_ids) & set(existing_ids):
        raise ValueError("GESIS adds duplicate or colliding index identities")
    args.output.mkdir(parents=True, exist_ok=True)
    for filename in ("inkar_metadata_2025.json", "inkar_metadata_2025_embeddings.npy", "inkar_metadata_2025_embeddings.npy.meta.json"):
        shutil.copy2(args.baseline / filename, args.output / filename)
    docs = [service._build_doc(service._normalise_geodb_row(row)) for row in additions]
    service._embedder = service._new_embedder()
    added_vectors, precision = service._encode_documents(docs, 64)
    metadata_path = args.output / "geodb_metadata.json"
    metadata_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    full_vectors = np.concatenate((vectors, added_vectors), axis=0)
    if not np.array_equal(full_vectors[:len(existing)], vectors):
        raise AssertionError("Existing vectors changed")
    service._save_embeddings(args.output / "geodb_metadata_embeddings.npy", full_vectors, metadata_path)
    info = json.loads((args.baseline / "geodb_build_info.json").read_text())
    per_source = dict(Counter(r["source_key"] for r in rows))
    info.update({"built": datetime.now(timezone.utc).isoformat(), "records": len(rows),
                 "sources": len(per_source), "per_source_key": per_source, "gesis_report": report,
                 "baseline_metadata_sha256": digest(base_path), "existing_records_unchanged": len(existing)})
    info["per_source"]["gesis"] = len(additions)
    (args.output / "geodb_build_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    result = {"built_at": info["built"], "model": service.model_name, "new_vector_precision": precision,
              "max_seq_length": service.embedding_max_seq_length, "existing_geodb_rows": len(existing),
              "new_gesis_rows": len(additions), "geodb_rows": len(rows),
              "inkar_rows": len(json.loads((args.output / "inkar_metadata_2025.json").read_text())),
              "existing_records_unchanged": True, "existing_vectors_unchanged": True,
              "preexisting_duplicate_item_ids": {k: v for k, v in existing_ids.items() if v > 1},
              "baseline_metadata_sha256": digest(base_path), "baseline_vectors_sha256": digest(vectors_path),
              "baseline_service_sha256": digest(args.baseline / "soep_rag_advisor.py"),
              "candidate_service_sha256": digest(ROOT / "backend/app/services/soep_rag_advisor.py"),
              "candidate_files": {p.name: digest(p) for p in args.output.iterdir() if p.is_file()}}
    (args.gesis / "INDEX_REPORT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
