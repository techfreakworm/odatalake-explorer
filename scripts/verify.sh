#!/usr/bin/env bash
# The verifier's gate. Run from anywhere inside the repo:  bash scripts/verify.sh [--allow-dirty]
#
# Steps (each prints PASS, FAIL or SKIP; the script exits non-zero if any step FAILs):
#   1. clean tree        git status --porcelain is empty (skipped with --allow-dirty)
#   2. deps              uv sync --frozen --extra rerank
#   3. unit tests        uv run pytest -q -m "not e2e"
#   4. hygiene           no secrets (plan §8 grep), no personal paths, no commit trailers on this branch
#   5. e2e               tests/e2e against a local ollama, holding .cache/ollama.lock (bounded wait, trap release)
#   6. docker            docker build -t ask-olake:verify .   (SKIP while there is no Dockerfile)
#
# Env: VERIFY_BASE (default soma/odatalake-explorer, the branch point for the trailer check),
#      VERIFY_LOCK_WAIT_S (default 600, how long to wait for the ollama lock).
set -uo pipefail

ALLOW_DIRTY=0
for arg in "$@"; do
  case "$arg" in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    *) echo "usage: bash scripts/verify.sh [--allow-dirty]" >&2; exit 2 ;;
  esac
done

ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2
BASE=${VERIFY_BASE:-soma/odatalake-explorer}
LOCK=.cache/ollama.lock
LOCK_WAIT_S=${VERIFY_LOCK_WAIT_S:-600}
FAILED=0
LOCK_OWNED=0
LOGDIR=$(mktemp -d)

release_lock() {
  if [ "$LOCK_OWNED" = 1 ]; then rm -rf "$LOCK"; LOCK_OWNED=0; fi
}
trap 'release_lock; rm -rf "$LOGDIR"' EXIT
trap 'exit 130' INT TERM

result() {  # result <PASS|FAIL|SKIP> <step> [detail]
  printf '%-4s  %-12s %s\n' "$1" "$2" "${3:-}"
  [ "$1" = FAIL ] && FAILED=1
  return 0
}

run_step() {  # run_step <step> <command...>: PASS/FAIL on the exit code, the output tail on failure
  local step=$1; shift
  if "$@" >"$LOGDIR/$step.log" 2>&1; then
    result PASS "$step" "$(tail -n 1 "$LOGDIR/$step.log")"
  else
    result FAIL "$step" "(exit $?) $*"
    tail -n 25 "$LOGDIR/$step.log" | sed 's/^/      | /'
  fi
}

# 1. clean tree
dirty=$(git status --porcelain)
if [ -z "$dirty" ]; then
  result PASS clean-tree
elif [ "$ALLOW_DIRTY" = 1 ]; then
  result SKIP clean-tree "--allow-dirty: $(printf '%s\n' "$dirty" | wc -l | tr -d ' ') changed path(s)"
else
  result FAIL clean-tree "uncommitted changes (use --allow-dirty to check a work in progress):"
  printf '%s\n' "$dirty" | head -n 20 | sed 's/^/      | /'
fi

# 2. dependencies, exactly as locked
run_step deps uv sync --frozen --extra rerank

# 3. unit tests (no network, no LLM)
run_step unit-tests uv run pytest -q -m "not e2e"

# 4. hygiene
secrets=$(git grep -nE '(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|api_key[[:space:]]*=[[:space:]]*"')
if [ -z "$secrets" ]; then result PASS secrets "plan §8 grep finds nothing"; else
  result FAIL secrets "possible keys in tracked files:"; printf '%s\n' "$secrets" | head -n 10 | sed 's/^/      | /'; fi

# Generic home-directory paths anywhere except docs/ and poc/ (both are clean today), data/ (the corpus snapshot
# quotes example paths from the upstream OLake docs: a macOS user "john" and a Linux "user") and this script (it
# holds the pattern). The operator's real home directory must not appear anywhere at all.
paths=$(git grep -nE '/Users/|/home/[a-z]' -- . ':!docs' ':!poc' ':!data' ':!scripts/verify.sh')
if [ "${#HOME}" -gt 5 ]; then
  home_hits=$(git grep -nF "$HOME" -- .)
else
  home_hits=""
fi
if [ -z "$paths$home_hits" ]; then result PASS paths "no personal paths in tracked files"; else
  result FAIL paths "personal paths in tracked files:"; printf '%s\n%s\n' "$paths" "$home_hits" | grep -v '^$' \
    | head -n 10 | cut -c1-200 | sed 's/^/      | /'; fi

if git rev-parse --verify -q "$BASE" >/dev/null; then
  trailers=$(git log "$BASE..HEAD" --format=%B | grep -inE 'co-authored-by|claude-session|generated with')
  n=$(git rev-list --count "$BASE..HEAD")
  if [ -z "$trailers" ]; then result PASS trailers "$n commit(s) since $BASE carry no trailers"; else
    result FAIL trailers "commit messages since $BASE carry trailers:"; printf '%s\n' "$trailers" | head | sed 's/^/      | /'; fi
else
  result FAIL trailers "base $BASE not found (set VERIFY_BASE)"
fi

# 5. e2e against a local ollama: one heavy ollama job at a time across the team
mkdir -p .cache
waited=0
while :; do
  if mkdir "$LOCK" 2>/dev/null; then LOCK_OWNED=1; break; fi
  if [ "$waited" -ge "$LOCK_WAIT_S" ]; then break; fi
  [ "$waited" = 0 ] && echo "      waiting for $LOCK (held by: $(cat "$LOCK/owner" 2>/dev/null || echo unknown))"
  sleep 10; waited=$((waited + 10))
done
if [ "$LOCK_OWNED" = 1 ]; then
  echo "api: scripts/verify.sh e2e (pid $$)" >"$LOCK/owner"
  run_step e2e env OLLAMA_LOCK_HELD=1 E2E_REQUIRED=1 uv run pytest -q -m e2e tests/e2e
  release_lock
else
  result FAIL e2e "ollama lock still held after ${LOCK_WAIT_S}s by: $(cat "$LOCK/owner" 2>/dev/null || echo unknown)"
fi

# 6. container image
if [ -f Dockerfile ]; then
  run_step docker docker build -t ask-olake:verify .
else
  result SKIP docker "no Dockerfile yet"
fi

if [ "$FAILED" = 0 ]; then echo "verify: PASS"; else echo "verify: FAIL"; fi
exit "$FAILED"
