#!/usr/bin/env bash
# Remove ONLY runtime telemetry copies, not primary logs, metadata or service backups.
# Supply the private backup root after sourcing the VM's existing credential environment.
# Default is a dry run; --apply is required to delete. Never write credentials into this repo.
set -euo pipefail
ROOT="${1:?usage: remove_legacy_telemetry_backups.sh <private-remote-root> [--apply]}"
FLAGS=(--dry-run)
if [[ "${2:-}" == --apply ]]; then FLAGS=(); fi
clean() {
  local path="$1"
  if rclone lsf "$path" --max-depth 1 >/dev/null 2>&1; then
    rclone delete "$path" "${FLAGS[@]}" --include 'queries-*.jsonl' --include 'feedback-*.jsonl' \
      --include 'privacy.sqlite3*' --include '.feedback-signing-key' --max-depth 1 -v
  fi
}
clean "$ROOT/geolab/opt/geolab/logs"
DIRECTORIES=$(rclone lsf "$ROOT/geolab/_archive" --dirs-only --max-depth 1)
while IFS= read -r directory; do
  directory="${directory%/}"
  if [[ "$directory" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    clean "$ROOT/geolab/_archive/$directory/geolab/logs"
  fi
done <<< "$DIRECTORIES"
