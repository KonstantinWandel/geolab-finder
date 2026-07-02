#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/destatis-rag"
STACK_DIR="$ROOT/deploy/secure-geolab"

docker rm -f geolab-quick-tunnel >/dev/null 2>&1 || true

cd "$STACK_DIR"
docker compose down
