#!/usr/bin/env bash
# Ask OLake deploy helper (plan §4.5 D1, §1.4, §2; research.md §5.5). Every cloud command is printed before it runs.
#
#   deploy/deploy.sh secrets       one-time Cloud Run setup: the service account and one Secret Manager secret per key
#   deploy/deploy.sh primary       Cloud Run, asia-south1: remote build from this directory (Dockerfile) and deploy
#   deploy/deploy.sh fallback      DigitalOcean App Platform, BLR: create the app, or update it, from .do/app.yaml
#   deploy/deploy.sh smoke URL     day-of checks against a deployed URL: /healthz, /readyz, one /ask contract check,
#                                  the olake.io-origin preflight, SSE timing; SMOKE_BURST=50 adds a concurrent burst
#
# Env (only what the subcommand needs is checked):
#   PROJECT            GCP project id (secrets, primary)
#   REGION             default asia-south1          SERVICE        default ask-olake
#   SA_NAME            default ask-olake-run        MEMORY         default 2Gi (1Gi minimum, 4Gi for bge-base/rerank)
#   CPU                default 1                    MIN_INSTANCES  default 1
#   LLM_API_KEY, LLM_FALLBACK_API_KEY, LLM_FALLBACK2_API_KEY, GITHUB_TOKEN    keys; any that is unset is skipped
#   DO_REPO            GitHub owner/name for App Platform (fallback)
#   DO_BRANCH          default main                 DO_APP_NAME    default ask-olake
#   DO_SIZE            default apps-s-1vcpu-2gb (apps-s-1vcpu-1gb minimum, apps-d-1vcpu-4gb for the upgrades)
#   SMOKE_BURST        default 0 (smoke): number of concurrent /ask requests in the burst check
#
# Files: deploy/env.yaml holds the non-secret settings. Each deploy writes a fresh CANARY to .canary and builds
# a gitignored deploy/*.deploy.yaml copy with it; keys never go into a file that git tracks.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

REGION=${REGION:-asia-south1}
SERVICE=${SERVICE:-ask-olake}
SA_NAME=${SA_NAME:-ask-olake-run}
MEMORY=${MEMORY:-2Gi}
CPU=${CPU:-1}
MIN_INSTANCES=${MIN_INSTANCES:-1}
DO_BRANCH=${DO_BRANCH:-main}
DO_APP_NAME=${DO_APP_NAME:-ask-olake}
DO_SIZE=${DO_SIZE:-apps-s-1vcpu-2gb}
ENV_FILE=deploy/env.yaml
# env var that holds a key -> its Secret Manager secret name
SECRET_PAIRS="LLM_API_KEY:llm-api-key LLM_FALLBACK_API_KEY:llm-fallback-api-key LLM_FALLBACK2_API_KEY:llm-fallback2-api-key GITHUB_TOKEN:github-token"

die() { echo "deploy.sh: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed ($2)"; }
require_env() {
  local v
  for v in "$@"; do
    [ -n "${!v:-}" ] || die "set $v first (export $v=...)"
  done
}
run() { printf '+'; printf ' %q' "$@"; printf '\n'; "$@"; }

# KEY: "value" lines of deploy/env.yaml (comments and blanks skipped), as KEY<TAB>value
env_pairs() {
  [ -f "$ENV_FILE" ] || die "$ENV_FILE is missing"
  sed -n -E 's/^([A-Z][A-Z0-9_]*):[[:space:]]*"?([^"]*)"?[[:space:]]*$/\1	\2/p' "$ENV_FILE"
}
env_value() { env_pairs | awk -F'\t' -v k="$1" '$1 == k { print $2 }'; }

yaml_quote() {
  local s=${1//\\/\\\\}
  s=${s//\"/\\\"}
  printf '"%s"' "$s"
}

new_canary() {
  need openssl "it generates the prompt-leak canary"
  CANARY=$(openssl rand -hex 8)
  printf '%s\n' "$CANARY" > .canary
  GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
  echo "canary written to .canary (export CANARY=\$(cat .canary) before running the eval); GIT_SHA $GIT_SHA"
}

# deploy/env.yaml plus this deploy's CANARY and GIT_SHA, for gcloud --env-vars-file (one flat string map)
# The Gemini fallback's base URL is pre-filled: without its key the app would log a config_warning at every start,
# so the rendered envs leave FALLBACK2 out unless its key is there (a secret on Cloud Run, the env var for DigitalOcean)
FALLBACK2_VARS='LLM_FALLBACK2_BASE_URL|LLM_FALLBACK2_MODEL|LLM_FALLBACK2_REASONING_EFFORT'

write_env_deploy() {  # write_env_deploy OUT [EXCLUDE_REGEX]
  local exclude="^(CANARY|GIT_SHA${2:+|$2})	"
  {
    env_pairs | grep -v -E "$exclude" | while IFS="$(printf '\t')" read -r k v; do
      printf '%s: %s\n' "$k" "$(yaml_quote "$v")"
    done
    printf 'CANARY: "%s"\nGIT_SHA: "%s"\n' "$CANARY" "$GIT_SHA"
  } > "$1"
}

# ----------------------------------------------------------------------------- secrets (one-time, Cloud Run)
cmd_secrets() {
  need gcloud "https://cloud.google.com/sdk/docs/install"
  require_env PROJECT
  local sa="$SA_NAME@$PROJECT.iam.gserviceaccount.com" pair var name done_any=0
  if gcloud iam service-accounts describe "$sa" --project "$PROJECT" >/dev/null 2>&1; then
    echo "service account $sa exists"
  else
    run gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" --display-name "Ask OLake on Cloud Run"
  fi
  for pair in $SECRET_PAIRS; do
    var=${pair%%:*}
    name=${pair#*:}
    if [ -z "${!var:-}" ]; then
      echo "skip $name: $var is not set"
      continue
    fi
    if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
      echo "+ gcloud secrets versions add $name --data-file=-   (value from \$$var on stdin)"
      printf %s "${!var}" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
    else
      echo "+ gcloud secrets create $name --replication-policy=automatic --data-file=-   (value from \$$var on stdin)"
      printf %s "${!var}" | gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic \
        --data-file=- >/dev/null
    fi
    run gcloud secrets add-iam-policy-binding "$name" --project "$PROJECT" \
      --member="serviceAccount:$sa" --role=roles/secretmanager.secretAccessor >/dev/null
    done_any=1
  done
  [ "$done_any" = 1 ] || echo "no keys were set: export LLM_API_KEY (and the fallbacks) and run this again"
}

# ----------------------------------------------------------------------------- primary: Cloud Run
cmd_primary() {
  need gcloud "https://cloud.google.com/sdk/docs/install"
  require_env PROJECT
  local sa="$SA_NAME@$PROJECT.iam.gserviceaccount.com" pair var name ver mapping="" refresh
  new_canary
  # --update-secrets only for the secrets that exist, each pinned to its newest enabled version
  for pair in $SECRET_PAIRS; do
    var=${pair%%:*}
    name=${pair#*:}
    gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1 || { echo "no secret $name: $var not set"; continue; }
    ver=$(gcloud secrets versions list "$name" --project "$PROJECT" --filter=state:enabled --sort-by=~createTime \
          --limit=1 --format='value(name)')
    [ -n "$ver" ] || { echo "secret $name has no enabled version: skipped"; continue; }
    mapping="${mapping:+$mapping,}$var=$name:${ver##*/}"
  done
  [ -n "$mapping" ] || echo "warning: no LLM key secrets: /ask will return the degraded answer (run: deploy/deploy.sh secrets)"
  case ",$mapping" in
    *,LLM_FALLBACK2_API_KEY=*) write_env_deploy deploy/env.deploy.yaml ;;
    *) write_env_deploy deploy/env.deploy.yaml "$FALLBACK2_VARS"
       echo "no llm-fallback2-api-key secret: the Gemini fallback is left out of the env" ;;
  esac
  local extra=()
  [ -n "$mapping" ] && extra+=(--update-secrets "$mapping")
  refresh=$(env_value REFRESH_INTERVAL_MIN)
  refresh=${REFRESH_INTERVAL_MIN:-${refresh:-0}}
  # the in-app index refresher needs CPU between requests (research.md §5.5)
  case "$refresh" in ''|0|0.0) ;; *) extra+=(--no-cpu-throttling) ;; esac
  run gcloud run deploy "$SERVICE" --source . --project "$PROJECT" --region "$REGION" --allow-unauthenticated \
    --service-account "$sa" --min-instances "$MIN_INSTANCES" --cpu "$CPU" --memory "$MEMORY" --timeout 60 \
    --env-vars-file deploy/env.deploy.yaml \
    --startup-probe httpGet.path=/readyz,periodSeconds=5,failureThreshold=24,timeoutSeconds=2 \
    --liveness-probe httpGet.path=/healthz,periodSeconds=30,timeoutSeconds=2 \
    ${extra[@]+"${extra[@]}"}
  local url
  url=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')
  echo "deployed: $url"
  echo "next: deploy/deploy.sh smoke $url"
}

# ----------------------------------------------------------------------------- fallback: DigitalOcean App Platform
render_do_spec() {  # render_do_spec OUT
  local out=$1 pair var
  [ -f .do/app.yaml ] || die ".do/app.yaml is missing"
  {
    sed -e "s#\${DO_APP_NAME}#$DO_APP_NAME#g" -e "s#\${DO_REPO}#$DO_REPO#g" -e "s#\${DO_BRANCH}#$DO_BRANCH#g" \
        -e "s#\${DO_SIZE}#$DO_SIZE#g" .do/app.yaml | sed '/^#ENVS#$/,$d'
    local exclude='^(CANARY|GIT_SHA)	'
    [ -n "${LLM_FALLBACK2_API_KEY:-}" ] || exclude="^(CANARY|GIT_SHA|$FALLBACK2_VARS)	"
    env_pairs | grep -v -E "$exclude" | while IFS="$(printf '\t')" read -r k v; do
      [ -n "$v" ] || continue
      printf '      - key: %s\n        value: %s\n        scope: RUN_TIME\n' "$k" "$(yaml_quote "$v")"
    done
    printf '      - key: CANARY\n        value: "%s"\n        scope: RUN_TIME\n' "$CANARY"
    printf '      - key: GIT_SHA\n        value: "%s"\n        scope: RUN_TIME\n' "$GIT_SHA"
    for pair in $SECRET_PAIRS; do
      var=${pair%%:*}
      [ -n "${!var:-}" ] || continue
      printf '      - key: %s\n        type: SECRET\n        value: %s\n        scope: RUN_TIME\n' "$var" "$(yaml_quote "${!var}")"
    done
  } > "$out"
}

cmd_fallback() {
  need doctl "https://docs.digitalocean.com/reference/doctl/how-to/install/"
  require_env DO_REPO
  local spec=deploy/do-app.deploy.yaml id
  new_canary
  umask 077
  trap 'rm -f deploy/do-app.deploy.yaml' EXIT  # the rendered spec holds the keys in clear text
  render_do_spec "$spec"
  [ -n "${LLM_API_KEY:-}" ] || echo "warning: LLM_API_KEY is not set: /ask will return the degraded answer"
  id=$(doctl apps list --format ID,Spec.Name --no-header | awk -v n="$DO_APP_NAME" '$2 == n { print $1; exit }')
  if [ -n "$id" ]; then
    run doctl apps update "$id" --spec "$spec" --wait
  else
    run doctl apps create --spec "$spec" --wait
    id=$(doctl apps list --format ID,Spec.Name --no-header | awk -v n="$DO_APP_NAME" '$2 == n { print $1; exit }')
  fi
  local url
  url=$(doctl apps get "$id" --format DefaultIngress --no-header)
  echo "deployed: $url"
  echo "next: deploy/deploy.sh smoke $url"
}

# ----------------------------------------------------------------------------- smoke: day-of checks 4-5
cmd_smoke() {
  need curl "it runs every check"
  [ $# -ge 1 ] || die "usage: deploy/deploy.sh smoke URL"
  local base=${1%/} fails=0 code tmp
  base=${base%/ask}
  tmp=$(mktemp -d)
  # shellcheck disable=SC2064  # expand now: $tmp is local and gone when the EXIT trap runs
  trap "rm -rf '$tmp'" EXIT
  check() { if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; fails=$((fails + 1)); fi; }

  code=$(curl -sS -m 10 -o "$tmp/healthz" -w '%{http_code}' "$base/healthz" || true)
  check "GET /healthz -> $code" "$([ "$code" = 200 ] && echo 0 || echo 1)"
  if command -v jq >/dev/null 2>&1; then { jq -c '.index' "$tmp/healthz" 2>/dev/null || true; } | sed 's/^/      index: /'; fi
  code=$(curl -sS -m 10 -o "$tmp/readyz" -w '%{http_code}' "$base/readyz" || true)
  check "GET /readyz -> $code $(cat "$tmp/readyz" 2>/dev/null)" "$([ "$code" = 200 ] && echo 0 || echo 1)"

  code=$(curl -sS -m 60 -o "$tmp/ask" -w '%{http_code}' "$base/ask" -H 'content-type: application/json' \
         -H 'Cache-Control: no-cache' -d '{"question":"How do I install OLake?"}' || true)
  local shape=1
  if python3 - "$tmp/ask" <<'PY' 2>/dev/null; then shape=0; fi
import json, re, sys
b = json.load(open(sys.argv[1]))
ok = (isinstance(b, dict) and set(b) == {"answer", "sources"} and isinstance(b["answer"], str) and b["answer"].strip()
      and isinstance(b["sources"], list) and all(isinstance(s, str) and re.match(r"https?://", s) for s in b["sources"]))
print("      sources:", b.get("sources") if isinstance(b, dict) else None)
sys.exit(0 if ok else 1)
PY
  check "POST /ask -> $code, body exactly {answer, sources}" "$([ "$code" = 200 ] && [ "$shape" = 0 ] && echo 0 || echo 1)"

  curl -sS -m 10 -o /dev/null -D "$tmp/preflight" -X OPTIONS "$base/ask" -H 'Origin: https://olake.io' \
    -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type' || true
  { grep -i '^access-control' "$tmp/preflight" 2>/dev/null || true; } | tr -d '\r' | sed 's/^/      /'
  check "CORS preflight from https://olake.io" "$(grep -qi '^access-control-allow-origin' "$tmp/preflight" 2>/dev/null && echo 0 || echo 1)"

  # events must arrive spread out over time, not in one burst at the end
  curl -sN -m 90 "$base/ask/stream" -H 'content-type: application/json' -H 'Cache-Control: no-cache' \
    -d '{"question":"How do I install OLake?"}' 2>/dev/null \
    | while IFS= read -r line; do [ -n "$line" ] && printf '%s %s\n' "$(date +%H:%M:%S)" "${line:0:80}"; done \
    > "$tmp/sse" || true
  head -n 12 "$tmp/sse" | sed 's/^/      /'
  local tokens seconds
  tokens=$(grep -c 'event: token' "$tmp/sse" || true)
  seconds=$(awk '/event: token/ { print $1 }' "$tmp/sse" | sort -u | wc -l | tr -d ' ')
  echo "      $tokens token events over $seconds distinct second(s)"
  check "SSE /ask/stream sends meta and done" "$(grep -q 'event: meta' "$tmp/sse" && grep -q 'event: done' "$tmp/sse" && echo 0 || echo 1)"

  local burst=${SMOKE_BURST:-0}
  if [ "$burst" -gt 0 ] 2>/dev/null; then
    seq "$burst" | xargs -P "$burst" -I{} curl -s -o /dev/null -m 120 -w '%{http_code} %{time_total}\n' "$base/ask" \
      -H 'content-type: application/json' -H 'Cache-Control: no-cache' \
      -d '{"question":"What sources does OLake support?"}' > "$tmp/burst" || true
    awk '{ n[$1]++; if ($2 > m) m = $2 } END { for (c in n) print "      HTTP", c, n[c]; print "      slowest_s", m }' "$tmp/burst"
    check "burst of $burst concurrent /ask: no 429 or 5xx" "$(awk '$1 == 429 || $1 >= 500 || $1 == 000 { bad++ } END { print (bad ? 1 : 0) }' "$tmp/burst")"
  fi
  [ "$fails" = 0 ] && echo "smoke: PASS" || { echo "smoke: $fails check(s) failed"; return 1; }
}

usage() { sed -n '2,24p' "$ROOT/deploy/deploy.sh" | sed 's/^# \{0,1\}//'; }

main() {
  case "${1:-}" in
    secrets) shift; cmd_secrets "$@" ;;
    primary) shift; cmd_primary "$@" ;;
    fallback) shift; cmd_fallback "$@" ;;
    smoke) shift; cmd_smoke "$@" ;;
    -h|--help|help|"") usage ;;
    *) usage; die "unknown subcommand: $1" ;;
  esac
}

# run only when executed (sourcing the file just defines the functions, e.g. to test the renderers)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
