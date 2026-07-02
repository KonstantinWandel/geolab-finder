#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/destatis-rag"
STACK_RUNNER="$ROOT/deploy/secure-geolab/run.sh"
AUTH_ENV_FILE="${GEOLAB_AUTH_ENV_FILE:-$ROOT/.geolab_public_demo.env}"
TUNNEL_NAME="geolab-quick-tunnel"
URL_FILE="$ROOT/.last_geolab_public_url"
INFO_FILE="$ROOT/.last_geolab_public_info"

if [[ ! -x "$STACK_RUNNER" ]]; then
  echo "Missing stack runner: $STACK_RUNNER" >&2
  exit 1
fi

"$STACK_RUNNER"

set -a
# shellcheck disable=SC1090
source "$AUTH_ENV_FILE"
set +a

extract_tunnel_url() {
  local logs
  logs="$(docker logs "$TUNNEL_NAME" 2>&1 || true)"
  if command -v rg >/dev/null 2>&1; then
    printf '%s\n' "$logs" | rg -o 'https://[-0-9a-z]+[.]trycloudflare[.]com' -m1 || true
  else
    printf '%s\n' "$logs" | grep -Eo 'https://[-0-9a-z]+[.]trycloudflare[.]com' | head -n1 || true
  fi
}

frontend_ready() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:15173 || true)"
  [[ "$code" == "200" || "$code" == "401" ]]
}

for _ in $(seq 1 90); do
  if curl -sf http://127.0.0.1:18000/health >/dev/null 2>&1 && frontend_ready; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:18000/health >/dev/null 2>&1; then
  echo "GeoLAB backend did not become ready on 127.0.0.1:18000" >&2
  exit 1
fi

if ! frontend_ready; then
  echo "GeoLAB frontend did not become ready on 127.0.0.1:15173" >&2
  exit 1
fi

docker rm -f "$TUNNEL_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$TUNNEL_NAME" \
  --network host \
  cloudflare/cloudflared:latest \
  tunnel --no-autoupdate --url http://127.0.0.1:15173 \
  >/dev/null

PUBLIC_URL=""
for _ in $(seq 1 60); do
  PUBLIC_URL="$(extract_tunnel_url)"
  if [[ -n "$PUBLIC_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "Quick Tunnel did not produce a public URL. Check: docker logs $TUNNEL_NAME" >&2
  exit 1
fi

printf '%s\n' "$PUBLIC_URL" > "$URL_FILE"
cat > "$INFO_FILE" <<EOF
URL=$PUBLIC_URL
USER=$GEOLAB_BASIC_AUTH_USER
PASSWORD=$GEOLAB_BASIC_AUTH_PASSWORD
EOF
chmod 600 "$INFO_FILE"

echo "URL=$PUBLIC_URL"
echo "USER=$GEOLAB_BASIC_AUTH_USER"
echo "PASSWORD=$GEOLAB_BASIC_AUTH_PASSWORD"
echo "STACK_LOGS=cd $ROOT/deploy/secure-geolab && docker compose logs -f --tail=100 geolab-backend geolab-frontend"
echo "TUNNEL_LOGS=docker logs -f $TUNNEL_NAME"
