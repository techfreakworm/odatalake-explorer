# WAKEUP: from a fresh checkout to a live, measured endpoint

Run these steps in order, from the repo root, in bash or zsh. Each step says what it costs and whether it reaches
outside this laptop:

- **[local]**: nothing leaves the laptop.
- **[outward]**: calls a third-party service or creates cloud resources.
- **[$]**: costs money (amounts from research.md §5.1 and §5.5).

## 0. Prerequisites [local]

```bash
uv --version && uv python find 3.12          # Python toolchain (uv python install 3.12 if missing)
docker info >/dev/null && echo docker-ok     # the image and the local container test
gcloud --version | head -1                   # primary host (Cloud Run)
doctl version                                # fallback host (DigitalOcean); only for step 10
ngrok version                                # emergency path; only for step 10
jq --version && openssl version && curl --version | head -1
git status --short && git log --oneline -1   # a clean tree at the commit you mean to ship
uv sync --frozen --extra rerank              # dependencies exactly as locked
uv run pytest -q -m "not e2e"                # unit tests, no network, no LLM
uv run python -m index.validate              # the committed index (data/index/CURRENT) is valid
```

`index.validate` ends with `valid`. The index is committed, so there is nothing to build.

## 1. Get the keys and fill `.env` [outward]

The LLM chain is tried in order (decision D7), so get the keys in this order:

1. **Primary: the event credits.** The organizers give the base URL, key and model (kickoff question K1). Use the
   lowest reasoning setting the model supports.
2. **Paid fallback, at least 100 RPM, with a spend cap.** One of:
   - OpenAI: https://platform.openai.com/api-keys, base `https://api.openai.com/v1`
   - Groq developer plan: https://console.groq.com/keys, base `https://api.groq.com/openai/v1`
   - DigitalOcean: the control panel's serverless inference page (a model access key, prepaid), base
     `https://inference.do-ai.run/v1`
3. **Last resort: Gemma 4 on the Gemini free tier.** A Google AI Studio key from
   https://aistudio.google.com/apikey (about 15 RPM, data used by Google).
4. **Optional: `GITHUB_TOKEN`.** A fine-grained token at https://github.com/settings/personal-access-tokens with
   read-only "Public repositories" access. It only matters for the index refresher.

```bash
cp .env.example .env
${EDITOR:-vi} .env     # fill LLM_*, LLM_FALLBACK_*, LLM_FALLBACK2_* (BASE_URL, API_KEY, MODEL, REASONING_EFFORT)
chmod 600 .env         # .env is gitignored; never commit it
```

## 2. Smoke-test every key [outward] [$: a few hundred tokens per key]

This is plan §2's credits smoke test, run once per provider in the chain:

```bash
set -a; source .env; set +a
smoke_key() {  # smoke_key BASE_URL API_KEY MODEL [REASONING_EFFORT]
  B="${1%/}"; H=(-H "Authorization: Bearer $2" -H 'Content-Type: application/json')
  echo "== models (check 3: the key works)"
  curl -sS "$B/models" "${H[@]}" | jq -r '.data[].id' | head -40
  echo "== one timed one-word completion, lowest reasoning setting (check 2: rate-limit headers)"
  curl -sS -D - -w '\nHTTP %{http_code} in %{time_total}s\n' "$B/chat/completions" "${H[@]}" \
    -d "{\"model\":\"$3\"${4:+,\"reasoning_effort\":\"$4\"},\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word OK.\"}]}" \
    | grep -i -E '^x-ratelimit|^retry-after|HTTP |"content"'
  echo "== streaming plus response_format (check 1)"
  curl -sN "$B/chat/completions" "${H[@]}" \
    -d "{\"model\":\"$3\",\"stream\":true,\"response_format\":{\"type\":\"json_object\"},\"messages\":[{\"role\":\"user\",\"content\":\"Reply with {\\\"ok\\\": true} as JSON.\"}]}" | head -5
  echo "== eight parallel calls (any 429: set MAX_CONCURRENCY below the limit)"
  seq 8 | xargs -P8 -I{} curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' "$B/chat/completions" "${H[@]}" \
    -d "{\"model\":\"$3\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK.\"}]}"
}
smoke_key "$LLM_BASE_URL" "$LLM_API_KEY" "$LLM_MODEL" "$LLM_REASONING_EFFORT"
smoke_key "$LLM_FALLBACK_BASE_URL" "$LLM_FALLBACK_API_KEY" "$LLM_FALLBACK_MODEL" "$LLM_FALLBACK_REASONING_EFFORT"
smoke_key "$LLM_FALLBACK2_BASE_URL" "$LLM_FALLBACK2_API_KEY" "$LLM_FALLBACK2_MODEL" "$LLM_FALLBACK2_REASONING_EFFORT"
```

**Go/no-go:**
- If the timed call fails, or takes more than 5 s for the one-word reply, move the next key in the chain up to
  primary now (swap the variables in `.env`), and tell the organizers.
- Any 429 among the eight parallel calls means the limit is tight. Set `MAX_CONCURRENCY` below it in
  `deploy/env.yaml` and `.env`.
- If streaming or `response_format` fails, note it and carry on: the app never depends on `response_format`, and the
  widget falls back to `POST /ask`.

## 3. One local answer with the real key [outward: one LLM call] [$: about 3.5k tokens]

```bash
uv run --env-file .env uvicorn app.main:app --port 8000      # terminal 1; wait for "Application startup complete"
curl -s http://127.0.0.1:8000/readyz                          # terminal 2: {"ready":true}
curl -si -X POST http://127.0.0.1:8000/ask -H 'content-type: application/json' \
  -d '{"question":"How do I install OLake UI with Docker Compose?"}' | grep -i -E '^x-ask-reason|^server-timing'
curl -s -X POST http://127.0.0.1:8000/ask -H 'content-type: application/json' \
  -d '{"question":"How do I install OLake UI with Docker Compose?"}' | jq .
```

A good answer has `X-Ask-Reason: answered`, `[1]`-style markers, and `sources` that start with
`https://olake.io/docs/`.
- `degraded_*` means no provider is configured, or the call failed. The answer lists pages but cites nothing.
- `retrieval_gate` means the off-topic gate fired.
Stop the server with Ctrl-C.

## 4. Google Cloud project, billing and APIs [outward] [$: billing must be enabled]

```bash
gcloud auth login
export PROJECT=<your-project-id>                              # gcloud projects list, or create one in the console
gcloud billing accounts list                                  # pick the ACCOUNT_ID
gcloud billing projects link "$PROJECT" --billing-account <ACCOUNT_ID>
gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 5. Secrets, once [outward] [$: Secret Manager, a few cents a month]

```bash
set -a; source .env; set +a                                   # puts the keys into the shell environment
deploy/deploy.sh secrets
```

This creates the service account `ask-olake-run` and one secret per key that is set: `llm-api-key`,
`llm-fallback-api-key`, `llm-fallback2-api-key` and `github-token`. A key that is not set is skipped. Running it
again adds a new version to each secret.

## 6. Deploy to Cloud Run [outward] [$: about $0.65 a day idle at 2 GiB with min-instances 1, plus Cloud Build]

```bash
deploy/deploy.sh primary
export URL=$(gcloud run services describe ask-olake --region asia-south1 --format 'value(status.url)')
export CANARY=$(cat .canary)                                  # the fresh prompt-leak canary of this deploy
```

The script echoes every command before it runs it:
- It builds remotely from this directory with the Dockerfile, so no image is uploaded from the laptop.
- It writes a fresh CANARY to `.canary`.
- It passes the non-secret settings from `deploy/env.yaml`.
- It maps only the secrets that exist, each pinned to its newest version.
- It adds `--no-cpu-throttling` when `REFRESH_INTERVAL_MIN` is above 0.

## 7. Post-deploy smoke [outward] [$: one answer, or 51 with the burst]

```bash
deploy/deploy.sh smoke "$URL"
SMOKE_BURST=50 deploy/deploy.sh smoke "$URL"                  # plan §2 check 5: a scorer-like burst
```

PASS looks like this. Every line starts with PASS, and the last line is `smoke: PASS`; the burst adds two
`HTTP 200 50`-style lines and one more PASS:

```text
PASS  GET /healthz -> 200
      index: {"version":"<data/index/CURRENT>", ...}
PASS  GET /readyz -> 200 {"ready":true}
PASS  POST /ask -> 200, body exactly {answer, sources}
PASS  CORS preflight from https://olake.io
PASS  SSE /ask/stream sends meta and done
PASS  burst of 50 concurrent /ask: no 429 or 5xx
smoke: PASS
```

Also check:
- The `index.version` in /healthz matches `cat data/index/CURRENT`.
- The `N token events over M distinct second(s)` line shows tokens spread over several seconds. All of them in one
  second means the stream is buffered; the widget then falls back to `/ask`.

## 8. Eval against the public URL [outward] [$: 94 answers plus the judge, about 0.4M tokens]

```bash
export CANARY=$(cat .canary)
JUDGE_BASE_URL=<openai-compatible base> JUDGE_API_KEY=<key> JUDGE_MODEL=<a strong model, another family> \
  uv run python -m eval.run --base-url "$URL" --concurrency 4 --timeout 60 --judge --judge-concurrency 2 \
  --label cloudrun --out eval/results/cloudrun.json
uv run python -m eval.report eval/results/cloudrun.json        # the Markdown table for the README
```

The results land in `eval/results/cloudrun.json`, with one row per question, the summary, and the server's
`/healthz` block. The run exits 1 on any contract failure or canary leak.
- Leave out `--judge` for the deterministic checks only. They are free apart from the 94 answers.
- Without the `JUDGE_*` variables, the judge falls back to the `LLM_*` model of the same name. That judges the
  generator with itself, and the results file flags it.

## 9. Recalibrate the gate, then redeploy [local, then outward] [$: one deploy]

The full run prints a calibration line:

```text
gate calibration: lowest must-answer gate score 0.7094 (SRC-11) - 0.02 = ABSTAIN_THRESHOLD 0.6894; must-abstain rows below it: 5/12
```

Put that threshold into `deploy/env.yaml` (`ABSTAIN_THRESHOLD: "0.6894"`), commit, and run
`deploy/deploy.sh primary` again. A free local equivalent, with no LLM: start a server with `DEBUG=1` and run
`uv run python -m eval.run --base-url http://127.0.0.1:8000 --retrieval-only`. It prints the same line from
`/debug/retrieve`.

## 10. Fallback host and emergency path

**DigitalOcean App Platform, BLR** [outward] [$: apps-s-1vcpu-2gb is $25 a month, billed per second]

App Platform builds from GitHub, so the repo must be pushed first, and App Platform needs access to it.

```bash
doctl auth init                                               # token: https://cloud.digitalocean.com/account/api/tokens
set -a; source .env; set +a                                   # the keys go into the spec as SECRET envs
DO_REPO=<owner>/<repo> deploy/deploy.sh fallback              # creates the app, or updates it on later runs
deploy/deploy.sh smoke https://<the printed DefaultIngress>
```

**Emergency: ngrok from this laptop** [outward: it exposes the laptop] [$: the free plan's one dev domain]

```bash
ngrok config add-authtoken <TOKEN>                            # https://dashboard.ngrok.com/get-started/your-authtoken
docker build -t ask-olake:local --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
NGROK_DOMAIN=<name>.ngrok-free.app deploy/ngrok.sh            # or: deploy/ngrok.sh uvicorn (no Docker)
```

The tunnel keeps the Mac awake (`caffeinate -dims`) until Ctrl-C.

## 11. Embed it [local]

Replace `HOST` with the deployed URL (for example `$URL`):

```html
<!-- any docs page: one line -->
<script src="https://HOST/widget.js" data-api="https://HOST" async></script>

<!-- where third-party scripts are not allowed: the host needs HOST in its frame-src -->
<iframe src="https://HOST/embed" title="Ask OLake" width="400" height="600" style="border:0"></iframe>
```

```js
// Docusaurus: docusaurus.config.js
scripts: [{src: 'https://HOST/widget.js', async: true, 'data-api': 'https://HOST'}],
```

The demo page at `https://HOST/` shows the widget with these snippets filled in.

## 12. Roll back and tear down [outward]

```bash
# Cloud Run: send all traffic to the previous revision
gcloud run revisions list --service ask-olake --region asia-south1
gcloud run services update-traffic ask-olake --region asia-south1 --to-revisions <REVISION>=100
# A bad index: point CURRENT at the previous version (kept next to it), commit, and redeploy
ls data/index && uv run python -c "from index.manifest import swap_current; from index.config import INDEX_DIR; swap_current(INDEX_DIR, '<VERSION>')"
# Tear down: the service, the secrets, the service account, the DigitalOcean app
gcloud run services delete ask-olake --region asia-south1
for s in llm-api-key llm-fallback-api-key llm-fallback2-api-key github-token; do gcloud secrets delete "$s" --quiet; done
gcloud iam service-accounts delete "ask-olake-run@$PROJECT.iam.gserviceaccount.com" --quiet
doctl apps list && doctl apps delete <APP_ID>
```
