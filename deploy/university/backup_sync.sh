#!/bin/bash
# Guarded mirror of one host tree to the Kuehne 20 TB share.
#
# THE DESIGN PROBLEM: a plain `rclone sync` is subtractive (intentional deletes propagate, which is
# wanted) but that is exactly what destroys the backup if the SOURCE is wiped by a crash. Three layers
# resolve it:
#   1. --backup-dir : deleted/superseded files are MOVED to _archive/<date>/ instead of destroyed.
#                     The live mirror is subtractive; nothing is actually lost for RETAIN_DAYS.
#   2. --max-delete : hard circuit breaker. A wiped source would try to delete everything and rclone
#                     aborts the whole run instead, changing nothing.
#   3. sentinel + size sanity: refuse to run at all if canary files are missing or the tree has
#                     collapsed versus the last recorded good run.
# Exit codes: 0 ok, 10 precheck refused (SAFE: nothing changed), 20 sync error.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../kuehne_env.sh"

NAME="${NAME:?set NAME}"                 # e.g. lovelace / geolab
SRC="${SRC:?set SRC}"                    # local dir to mirror
DEST="${DEST:?set DEST}"                 # rclone path of the live mirror
ARCHIVE_ROOT="${ARCHIVE_ROOT:?set ARCHIVE_ROOT}"
STATE_DIR="${STATE_DIR:-$MY_ROOT/_state}"
SENTINELS="${SENTINELS:-}"               # space-separated paths that MUST exist under SRC
MAX_DELETE="${MAX_DELETE:-20000}"        # abort if a run would remove more than this many files
MIN_FRACTION="${MIN_FRACTION:-60}"       # refuse if source is < this % of last good size
RETAIN_DAYS="${RETAIN_DAYS:-45}"
EXCLUDES=(--exclude '**/__pycache__/**' --exclude '*.pid' --exclude '**/.ipynb_checkpoints/**'
          # Private finder telemetry has its own 90-day retention and must not reappear in backups.
          --exclude 'geolab/logs/**' --exclude '**/geolab/logs/**'
          --exclude '.local/**' --exclude '**/.cache/**' --exclude '**/node_modules/**'
          --exclude '**/.vscode-server/**' --exclude '**/.git/objects/pack/tmp_*'
          --exclude '**/*.env' --exclude '**/.*_secret*' --exclude '**/*.smbcreds'
          # ffmpeg output, regenerable from raw/: ~230 GB in ~210k tiny files that would otherwise
          # dominate every run (SMB is round-trip-bound). See _EXCLUDED_README.txt on the share.
          --exclude '**/interim/audio/**' --exclude '**/interim/frames/**'
          # The sync's OWN log. rclone was copying the file it was writing to, the size changed
          # mid-transfer, and "corrupted on transfer: sizes differ" aborted the whole run after
          # five retries. That is why 14 of the geolab host's 16 nightly runs failed. Any live
          # log has this problem; these two are the ones the backup itself writes.
          # Both forms: an rclone pattern beginning with **/ did NOT match the path at the
          # source root ('backup_sync/logs/...'), which is exactly where these live.
          --exclude 'deploy_backup/logs/**' --exclude 'backup_sync/logs/**'
          --exclude '**/deploy_backup/logs/**' --exclude '**/backup_sync/logs/**')
LOG="$HERE/../logs/sync_${NAME}.log"; mkdir -p "$(dirname "$LOG")"
# single-instance lock: the first full run can take days, so the next scheduled trigger must not stack
LOCK="$HERE/../logs/.lock_${NAME}"
exec 9>"$LOCK"
flock -n 9 || { echo "[$(date -u +%FT%TZ)] another '$NAME' sync is still running; skipping this trigger" >> "$LOG"; exit 0; }
say(){ echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

say "=== sync '$NAME' start ==="

# ---- guard 1: sentinels ------------------------------------------------------------------
for s in $SENTINELS; do
  [ -e "$SRC/$s" ] || { say "REFUSE: sentinel missing: $SRC/$s (source looks wiped/not mounted)"; exit 10; }
done

# ---- guard 2: size sanity vs last good run -----------------------------------------------
cur_bytes=$(du -sb "$SRC" 2>/dev/null | cut -f1); cur_bytes=${cur_bytes:-0}
[ "$cur_bytes" -gt 0 ] || { say "REFUSE: source measured 0 bytes"; exit 10; }
prev=$(rclone cat "$STATE_DIR/$NAME.bytes" 2>/dev/null | tr -dc '0-9')
if [ -n "${prev:-}" ] && [ "$prev" -gt 0 ]; then
  pct=$(( cur_bytes * 100 / prev ))
  say "source=$cur_bytes bytes; last good=$prev ($pct% of previous)"
  if [ "$pct" -lt "$MIN_FRACTION" ]; then
    say "REFUSE: source shrank to $pct% (< $MIN_FRACTION%). Suspected data loss; NOT syncing."
    say "        If this shrink was intentional, re-run with MIN_FRACTION=0 to override."
    exit 10
  fi
else
  say "no previous state recorded; treating this as the baseline run"
fi

# ---- the sync ----------------------------------------------------------------------------
STAMP=$(date -u +%F)
say "syncing -> $DEST   (deletions/overwrites archived to $ARCHIVE_ROOT/$STAMP)"
rclone sync "$SRC" "$DEST" \
  --backup-dir "$ARCHIVE_ROOT/$STAMP" \
  --max-delete "$MAX_DELETE" \
  --transfers 4 --checkers 8 \
  --low-level-retries 20 --retries 5 --retries-sleep 10s \
  --timeout 5m --contimeout 1m \
  --stats 10m --stats-one-line --log-level INFO --log-file "$LOG" \
  "${EXCLUDES[@]}"
rc=$?
if [ $rc -ne 0 ]; then
  say "SYNC ERROR rc=$rc (nothing was force-deleted; --max-delete aborts rather than proceeding)"
  exit 20
fi

# ---- record state + prune old archives ---------------------------------------------------
echo "$cur_bytes" | rclone rcat "$STATE_DIR/$NAME.bytes" 2>/dev/null
echo "$(date -u +%FT%TZ) bytes=$cur_bytes" | rclone rcat "$STATE_DIR/$NAME.last" 2>/dev/null
say "recorded state: $cur_bytes bytes"
cutoff=$(date -u -d "$RETAIN_DAYS days ago" +%F 2>/dev/null)
if [ -n "$cutoff" ]; then
  rclone lsf --dirs-only "$ARCHIVE_ROOT" 2>/dev/null | tr -d '/' | while read -r d; do
    case "$d" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
      [[ "$d" < "$cutoff" ]] && { say "pruning archive $d (older than $RETAIN_DAYS days)"; rclone purge "$ARCHIVE_ROOT/$d" 2>/dev/null; } ;;
    esac
  done
fi
say "=== sync '$NAME' done ok ==="
