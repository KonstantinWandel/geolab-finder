#!/usr/bin/env python3
"""Recompute SOEP + INKAR bi-encoder embeddings with the current document
construction (missing-value boilerplate stripped) and save them next to the
metadata JSON, so serving containers load them from cache instead of embedding
the whole corpus on first query.

Run inside the backend image so the embedding model and the document-building
code exactly match the serving runtime, e.g.:

  docker run --rm --gpus all \
    -e GEOLAB_APP_MODE=all -e SOEP_RAG_DEVICE=cuda \
    -e SOEP_RAG_METADATA_PATH=/app/data/soep/soep_metadata_enriched.json \
    -e SOEP_METADATA_ROOT=/app/data/soep -e HF_HOME=/cache/hf \
    -v "$PWD/soep_metadata_output:/app/data/soep" \
    -v /home/researcher/hf_cache:/cache/hf \
    -v "$PWD/scripts/rebuild_embeddings.py:/app/rebuild_embeddings.py" \
    <backend-image> python /app/rebuild_embeddings.py
"""
import json
import os

os.environ.setdefault("GEOLAB_APP_MODE", "all")

from app.services.soep_rag_advisor import SOEPRagAdvisorService


def main() -> None:
    svc = SOEPRagAdvisorService()
    batch = int(os.getenv("REEMBED_BATCH_SIZE", "64"))
    summary = svc.build_and_save_embeddings(batch_size=batch)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
