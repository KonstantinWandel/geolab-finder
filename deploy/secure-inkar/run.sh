#!/usr/bin/env bash
# Build + run the INKAR-only GeoLAB stack (backend + Caddy frontend + cloudflare
# quick tunnel). Generates a basic-auth credential on first run and stores it in
# .auth.env (chmod 600, git-ignored). Docker needs sudo on this host.
set -euo pipefail
cd "$(dirname "$0")"

APP_USER="${APP_USER:-inkar}"
AUTH_FILE=".auth.env"

if [[ ! -f "$AUTH_FILE" ]]; then
  umask 077
  PW="$(python3 -c 'import secrets,string;print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(20)))')"
  printf 'GEOLAB_BASIC_AUTH_USER=%s\nGEOLAB_BASIC_AUTH_PASSWORD=%s\n' "$APP_USER" "$PW" >"$AUTH_FILE"
  chmod 600 "$AUTH_FILE"
fi

set -a
# shellcheck disable=SC1090
source "$AUTH_FILE"
set +a

HASH="$(sudo docker run --rm --entrypoint caddy caddy:2-alpine hash-password --plaintext "$GEOLAB_BASIC_AUTH_PASSWORD" | tr -d '\r')"

sudo env GEOLAB_BASIC_AUTH_USER="$GEOLAB_BASIC_AUTH_USER" GEOLAB_BASIC_AUTH_HASH="$HASH" \
  docker compose up -d --build "$@"

echo "INKAR stack up. User: $GEOLAB_BASIC_AUTH_USER  Password: $GEOLAB_BASIC_AUTH_PASSWORD"
echo "Public URL (after ~10s): sudo docker compose logs cloudflared | grep trycloudflare"
