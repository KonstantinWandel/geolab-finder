#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/destatis-rag"
STACK_DIR="$ROOT/deploy/secure-geolab"
AUTH_ENV_FILE="${GEOLAB_AUTH_ENV_FILE:-$ROOT/.geolab_public_demo.env}"

ensure_auth_env() {
  if [[ ! -f "$AUTH_ENV_FILE" ]]; then
    mkdir -p "$(dirname "$AUTH_ENV_FILE")"
    umask 077
    python3 - <<'PY' > "$AUTH_ENV_FILE"
import secrets
import string

alphabet = string.ascii_letters + string.digits
password = "".join(secrets.choice(alphabet) for _ in range(24))
print("GEOLAB_BASIC_AUTH_USER=geolab_guest")
print(f"GEOLAB_BASIC_AUTH_PASSWORD={password}")
PY
    chmod 600 "$AUTH_ENV_FILE"
  fi

  set -a
  # shellcheck disable=SC1090
  source "$AUTH_ENV_FILE"
  set +a

  if [[ -z "${GEOLAB_BASIC_AUTH_USER:-}" || -z "${GEOLAB_BASIC_AUTH_PASSWORD:-}" ]]; then
    echo "GeoLAB auth env is incomplete: $AUTH_ENV_FILE" >&2
    exit 1
  fi

  export GEOLAB_BASIC_AUTH_HASH
  GEOLAB_BASIC_AUTH_HASH="$(docker run --rm --entrypoint caddy caddy:2-alpine hash-password --plaintext "$GEOLAB_BASIC_AUTH_PASSWORD" | tr -d '\r')"
}

cd "$STACK_DIR"

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created $STACK_DIR/.env from .env.example"
fi

ensure_auth_env

docker compose -f compose.yml up -d --build "$@"
