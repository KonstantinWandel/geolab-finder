#!/usr/bin/env bash
# Run on the university VM after staging the selected code/config and both frontend builds.
# No model, metadata, authentication or index changes. Keeps previous public bundles available.
set -euo pipefail
STAGE="${1:?usage: install_privacy.sh <stage-directory>}"
BACKUP="/opt/geolab/backups/privacy_$(date -u +%Y%m%d-%H%M%S)"
sudo caddy validate --config "$STAGE/config/Caddyfile" --adapter caddyfile
sudo mkdir -p "$BACKUP/backend/app/services" "$BACKUP/config" "$BACKUP/sites"
sudo chmod 700 "$BACKUP"
sudo cp -a /opt/geolab/app/destatis-rag/backend/app/main.py "$BACKUP/backend/app/"
sudo cp -a /opt/geolab/app/destatis-rag/backend/app/services/usage_log.py "$BACKUP/backend/app/services/"
sudo cp -a /etc/caddy/Caddyfile /home/kwandel/backup_sync/sync/backup_sync.sh "$BACKUP/config/"
sudo cp -a /opt/geolab/sites/soep /opt/geolab/sites/inkar "$BACKUP/sites/"
echo "Configuration/code backup: $BACKUP (no private telemetry copied)"

sudo rsync -a "$STAGE/code/backend/app/" /opt/geolab/app/destatis-rag/backend/app/
sudo install -o geolab -g geolab -m 644 "$STAGE/code/scripts/privacy_admin.py" /opt/geolab/app/destatis-rag/scripts/privacy_admin.py
sudo chown geolab:geolab /opt/geolab/app/destatis-rag/backend/app/main.py \
  /opt/geolab/app/destatis-rag/backend/app/services/{usage_log,privacy_store}.py
sudo chmod 750 /opt/geolab/logs
sudo find /opt/geolab/logs -maxdepth 1 -type f -exec chmod 600 {} +

sudo install -m 644 "$STAGE/config/geolab-privacy-retention.service" "$STAGE/config/geolab-privacy-retention.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now geolab-privacy-retention.timer
sudo systemctl start geolab-privacy-retention.service

sudo install -o kwandel -g kwandel -m 755 "$STAGE/config/backup_sync.sh" /home/kwandel/backup_sync/sync/backup_sync.sh
sudo install -m 644 "$STAGE/config/Caddyfile" /etc/caddy/Caddyfile
sudo chmod 600 /var/log/caddy/access.log
sudo systemctl reload caddy

for mode in soep inkar; do
  sudo systemctl restart "geolab-$mode"
  port=18001
  [[ "$mode" == inkar ]] && port=18002
  ready=false
  for attempt in $(seq 1 120); do
    if curl -fsS -m 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then ready=true; break; fi
    sleep 2
  done
  if [[ "$ready" != true ]]; then echo "Backend $mode did not become ready"; exit 1; fi
  echo "Backend $mode ready"
  sudo rsync -a --delete --exclude 'assets/**' "$STAGE/site_$mode/" "/opt/geolab/sites/$mode/"
  sudo rsync -a "$STAGE/site_$mode/assets/" "/opt/geolab/sites/$mode/assets/"
  sudo chown -R geolab:geolab "/opt/geolab/sites/$mode"
done
sudo systemctl is-active caddy geolab-soep geolab-inkar geolab-privacy-retention.timer
