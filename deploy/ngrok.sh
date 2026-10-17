#!/usr/bin/env bash
# Emergency host (plan §1.1, §11): serve Ask OLake from this laptop through an ngrok dev domain.
#
#   NGROK_DOMAIN=<name>.ngrok-free.app deploy/ngrok.sh [docker|uvicorn]
#
#   docker   (default) run the local image (IMAGE, default ask-olake:local; build it first with
#            docker build -t ask-olake:local .) with the keys from .env
#   uvicorn  run the app straight from this checkout (uv run --env-file .env uvicorn ...)
#
# Env: NGROK_DOMAIN (required; the free plan's one dev domain), PORT (local port, default 8080), IMAGE.
# On macOS the laptop is kept awake (caffeinate -dims) for as long as the tunnel runs. Ctrl-C stops it all.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

MODE=${1:-docker}
PORT=${PORT:-8080}
IMAGE=${IMAGE:-ask-olake:local}
NAME=ask-olake-ngrok

die() { echo "ngrok.sh: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed ($2)"; }

need ngrok "https://ngrok.com/download, then: ngrok config add-authtoken <TOKEN>"
need curl "it waits for /readyz"
[ -n "${NGROK_DOMAIN:-}" ] || die "set NGROK_DOMAIN to your ngrok dev domain (e.g. export NGROK_DOMAIN=name.ngrok-free.app)"
[ -f .env ] || echo "warning: no .env: the app starts without LLM keys and /ask returns the degraded answer"

APP_PID=""
cleanup() {
  if [ "$MODE" = docker ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; fi
  if [ -n "$APP_PID" ]; then kill "$APP_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

case "$MODE" in
  docker)
    need docker "https://docs.docker.com/get-docker/"
    docker image inspect "$IMAGE" >/dev/null 2>&1 || die "no image $IMAGE: run docker build -t $IMAGE ."
    env_args=()
    [ -f .env ] && env_args+=(--env-file .env)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    # -e after --env-file wins: the image's baked model paths and its port 8080 beat a .env written for host runs
    docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8080" ${env_args[@]+"${env_args[@]}"} \
      -e FASTEMBED_CACHE_PATH=/app/models -e TIKTOKEN_CACHE_DIR=/app/models/tiktoken -e PORT=8080 \
      -e "PUBLIC_BASE_URL=https://$NGROK_DOMAIN" "$IMAGE" >/dev/null
    ;;
  uvicorn)
    need uv "https://docs.astral.sh/uv/"
    env_args=()
    [ -f .env ] && env_args+=(--env-file .env)
    PUBLIC_BASE_URL="https://$NGROK_DOMAIN" uv run ${env_args[@]+"${env_args[@]}"} \
      uvicorn app.main:app --host 127.0.0.1 --port "$PORT" &
    APP_PID=$!
    ;;
  *) die "unknown mode $MODE (docker or uvicorn)" ;;
esac

echo "waiting for http://127.0.0.1:$PORT/readyz ..."
for _ in $(seq 1 120); do
  if curl -sf "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1 || die "the app did not become ready (docker logs $NAME)"
echo "ready; public URL: https://$NGROK_DOMAIN   (smoke it: deploy/deploy.sh smoke https://$NGROK_DOMAIN)"

if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -dims ngrok http --url="$NGROK_DOMAIN" "$PORT"
else
  ngrok http --url="$NGROK_DOMAIN" "$PORT"
fi
