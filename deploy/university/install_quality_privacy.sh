#!/usr/bin/env bash
# Selected-code deployment only. No models, indexes, Caddy changes or private-log backups.
set -euo pipefail
STAGE="${1:?usage: install_quality_privacy.sh <stage-directory>}"
ROOT=/opt/geolab/app/destatis-rag
BACKUP="/opt/geolab/backups/quality_privacy_$(date -u +%Y%m%d-%H%M%S)"
sudo mkdir -p "$BACKUP/backend/app/services" "$BACKUP/sites"
sudo chmod 700 "$BACKUP"
sudo cp -a "$ROOT/backend/app/main.py" "$BACKUP/backend/app/"
for name in privacy_store soep_rag_advisor usage_log; do
  sudo cp -a "$ROOT/backend/app/services/$name.py" "$BACKUP/backend/app/services/"
done
sudo cp -a /opt/geolab/sites/soep /opt/geolab/sites/inkar "$BACKUP/sites/"
echo "Code/public-site rollback copy: $BACKUP; no raw logs copied."

sudo systemctl stop geolab-privacy-retention.timer
trap 'sudo systemctl start geolab-soep geolab-inkar geolab-privacy-retention.timer' EXIT
sudo systemctl stop geolab-soep geolab-inkar
sudo rsync -a "$STAGE/code/backend/app/" "$ROOT/backend/app/"
for name in privacy_admin redact_legacy_queries; do
  sudo install -o geolab -g geolab -m 644 "$STAGE/code/scripts/$name.py" "$ROOT/scripts/$name.py"
done
sudo chown geolab:geolab "$ROOT/backend/app/main.py" "$ROOT/backend/app/services/"{privacy_store,soep_rag_advisor,usage_log}.py
for mode in soep inkar; do
  sudo mkdir -p "/etc/systemd/system/geolab-$mode.service.d"
  sudo install -m 644 "$STAGE/config/legacy_query_guard.conf" "/etc/systemd/system/geolab-$mode.service.d/privacy-legacy-log.conf"
done
sudo systemctl daemon-reload
sudo -u geolab /opt/geolab/.venv/bin/python "$ROOT/scripts/redact_legacy_queries.py"
sudo -u geolab /opt/geolab/.venv/bin/python "$ROOT/scripts/redact_legacy_queries.py" --apply
sudo -u geolab /opt/geolab/.venv/bin/python "$ROOT/scripts/privacy_admin.py" purge
sudo systemctl start geolab-soep geolab-inkar geolab-privacy-retention.timer
for mode in soep inkar; do
  port=18001
  [[ "$mode" == inkar ]] && port=18002
  ready=false
  for attempt in $(seq 1 120); do
    if curl -fsS -m 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then ready=true; break; fi
    sleep 2
  done
  [[ "$ready" == true ]] || { echo "Backend $mode did not become ready"; exit 1; }
  sudo rsync -a --delete --exclude 'assets/**' "$STAGE/site_$mode/" "/opt/geolab/sites/$mode/"
  sudo rsync -a "$STAGE/site_$mode/assets/" "/opt/geolab/sites/$mode/assets/"
  sudo chown -R geolab:geolab "/opt/geolab/sites/$mode"
  echo "Backend and frontend $mode ready."
done
sudo systemctl is-active geolab-soep geolab-inkar geolab-privacy-retention.timer
