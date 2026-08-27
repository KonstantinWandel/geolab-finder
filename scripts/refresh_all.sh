#!/usr/bin/env bash
# One command that refreshes the whole GeoDB index: re-fetch what is public, rebuild the
# records, re-embed on the GPU, run the retrieval gate, deploy, and regenerate the tracker.
#
# Scheduling note: this box is a Kubernetes pod, so /etc/cron.d is wiped on restart and there is
# no user systemd, which means a cron entry here does NOT survive. Options, in order of how much
# they actually hold: (a) run this by hand after a source publishes an update, which is the
# current practice; (b) a scheduled Claude Code session that runs it; (c) a systemd timer on the
# geolab VM, which is a real VM and persists, at the price of embedding on 4 CPU cores instead of
# the H200 (about 30 to 60 minutes for 10k records instead of 2).
#
# Usage: bash scripts/refresh_all.sh [--no-deploy]
set -euo pipefail
cd "$(dirname "$0")/.."
E=/home/researcher/miniconda3/envs/geolab-rag/bin/python
DEPLOY=1
[[ "${1:-}" == "--no-deploy" ]] && DEPLOY=0

echo "[1/6] fetching what is publicly downloadable"
$E scripts/fetch_sources.py

echo "[2/6] rebuilding the records"
$E scripts/build_geodb_metadata.py

echo "[3/6] re-embedding (GPU)"
( cd backend && GEOLAB_APP_MODE=inkar SOEP_RAG_DEVICE=cuda \
    INKAR_METADATA_ROOT="$PWD/../soep_metadata_output" \
    SOEP_METADATA_ROOT="$PWD/../soep_metadata_output" \
    $E -c "import warnings;warnings.filterwarnings('ignore');from app.services.soep_rag_advisor import SOEPRagAdvisorService as S;print(S().build_and_save_embeddings(64))" )

echo "[4/6] retrieval gate"
GEOLAB_APP_MODE=inkar SOEP_RAG_DEVICE=cuda \
  INKAR_METADATA_ROOT="$PWD/soep_metadata_output" SOEP_METADATA_ROOT="$PWD/soep_metadata_output" \
  SOEP_RAG_CACHE_DIR="$PWD/soep_metadata_output/cache" \
  SOEP_RAG_RERANKER_MODEL=BAAI/bge-reranker-base SOEP_RAG_RERANK_CANDIDATES=16 \
  $E scripts/eval_geodb_search.py --json-out output/eval_latest.json | tail -8

if [[ "$DEPLOY" == "1" ]]; then
  echo "[5/6] deploying"
  rsync -az soep_metadata_output/geodb_metadata.json \
            soep_metadata_output/geodb_metadata_embeddings.npy \
            soep_metadata_output/geodb_metadata_embeddings.npy.meta.json \
            soep_metadata_output/geodb_build_info.json vm:/home/kwandel/geodb_stage/
  ssh vm 'set -e
    D=/opt/geolab/app/destatis-rag
    for f in geodb_metadata.json geodb_metadata_embeddings.npy geodb_metadata_embeddings.npy.meta.json geodb_build_info.json; do
      sudo install -o geolab -g geolab -m 664 ~/geodb_stage/$f $D/soep_metadata_output/
    done
    sudo systemctl restart geolab-inkar'
  for _ in $(seq 1 40); do
    ssh vm 'curl -s -m 10 http://127.0.0.1:18002/health' | grep -q ok && { echo "  healthy"; break; }
    sleep 15
  done
else
  echo "[5/6] deploy skipped (--no-deploy)"
fi

echo "[6/6] regenerating the tracker and the handoff table"
$E scripts/build_status_report.py
echo "done"
