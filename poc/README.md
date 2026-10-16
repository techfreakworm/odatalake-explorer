# Ask OLake: validation POCs

Small, readable code that produces the measured numbers the research doc cites. It
is not the product. Everything runs locally; no cloud keys are needed.

## Setup

```bash
cd poc
export ASK_OLAKE_CACHE=/some/dir/outside/the/repo     # HTML, clones, corpus, models, embeddings
export UV_PROJECT_ENVIRONMENT=/some/venv/outside/the/repo
export TIKTOKEN_CACHE_DIR=$ASK_OLAKE_CACHE/tiktoken FASTEMBED_CACHE_PATH=$ASK_OLAKE_CACHE/models HF_HOME=$ASK_OLAKE_CACHE/hf
uv sync                                   # Python 3.12 (pinned in .python-version)
```

Modules run with `python -I` (isolated mode), so nothing from the current directory
or from downloaded data is importable. Downloaded HTML and clones live only under
`$ASK_OLAKE_CACHE` and are never executed.

LLM: any OpenAI-compatible endpoint. The default is local ollama
(`LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=qwen3:32b`). The event's
credits provider is a drop-in swap via `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`.
The judge reads `JUDGE_BASE_URL`, `JUDGE_API_KEY` and `JUDGE_MODEL`.

## Steps

| # | What | Command (from `poc/`) | Output |
|---|---|---|---|
| 1 | Docs fetch: sitemap → `/docs/` pages → Markdown (anchors, code language, tables, every tab panel). Add `--blog` for blog posts, measured separately; `--offline` re-extracts from cached HTML | `uv run python -I -m ingest.docs --blog` | `$CACHE/corpus/docs.jsonl`, `blog.jsonl` |
| 1 | Repos: shallow clones + allowlist | `uv run python -I -m ingest.repos` | `$CACHE/corpus/repos.jsonl` |
| 2 | Corpus stats | `uv run python -I -m ingest.stats` | `results/corpus.json` |
| 3 | Chunking at two target sizes | `uv run python -I -m chunking.chunker --target 300 --target 600` | `$CACHE/index/chunks-*.jsonl`, `results/chunks.json` |
| 4 | Retrieval benchmark | `uv run python -I -m retrieval.bench --target 300 --target 600 --dense BAAI/bge-small-en-v1.5 --dense BAAI/bge-base-en-v1.5 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --repeat 2` | `results/retrieval.json` |
| 5 | Answer + abstain probe | `uv run python -I -m answer.probe --think-probe` | `results/answer.json` |
| 6 | Scorer for any `/ask` URL | `uv run python -I -m eval.score --url http://127.0.0.1:8000/ask` | `results/eval_run.json` |
| 7 | API + widget, served from two origins | `uv run uvicorn api.app:app --host 127.0.0.1 --port 8000` and `uv run python -I -m http.server 8081 --bind 127.0.0.1 --directory api/demo` | open `http://127.0.0.1:8081/` |
| 8 | Freshness probe | `uv run python -I -m freshness.probe` | `results/freshness.json` |

The eval harness reads either `eval/seed.jsonl` (the provisional 18 questions) or the
canonical table in `docs/eval-questions.md`; pass `--questions ../docs/eval-questions.md`.

## Repo allowlist (decided by inspection)

| Repo | Kept | Skipped |
|---|---|---|
| olake (Go) | README/CONTRIBUTING, `drivers/*/README.md`, destination and example READMEs, `docker-compose*.yml`, `drivers/*/resources/spec.json` + `destination/*/resources/spec.json` (config schemas with descriptions and defaults), `protocol/*.go` (cobra commands; `root.go` holds every CLI flag with its default), `drivers/*/internal/config.go`, `destination/*/config.go`, `utils/ssh.go`, `utils/ssl.go`, `constants/*.go` | tests and testdata, `.github`, the Java writer sources, `go.mod`/`go.sum`, Makefiles |
| olake-ui (TS + Go server) | README, CONTRIBUTING, `api-contract.md`, server and ui READMEs, the three docker-compose files, `server/conf/app.yaml`, `server/internal/appconfig/*.go` | the TS/TSX sources, `swagger.json` (158 KB; the docs site already has an API page), lockfiles, tests |
| olake-helm | README, chart README, UNINSTALL_GUIDE, `Chart.yaml`, `values.yaml`, worker README | `templates/*` (Go-templated YAML that duplicates `values.yaml`), `values.schema.json`, worker Go code |
| olake-fusion (Java, a fork of Apache Amoro) | README, CONTRIBUTING, docker README, `charts/amoro/{Chart.yaml,values.yaml,README.md}`, `dist/.../conf/config.yaml`, `local-test/{docker-compose.yml,config.yaml}` | `docs/**` (upstream Amoro docs that never mention OLake; the OLake Fusion docs live at olake.io/docs/fusion), `site/**`, Java/Scala sources, `CLAUDE.md` |

Result: 84 files.

## Citation format

* Docs chunk: `https://olake.io/docs/<page>/#<anchor>`, where the anchor is the heading id of the section the chunk starts in.
* Repo chunk: `https://github.com/datazip-inc/<repo>/blob/<sha>/<path>#L<a>-L<b>`, pinned to the indexed commit.
  Markdown files get `?plain=1` before the fragment. GitHub only honours line anchors on
  the source view, and the rendered Markdown view ignores `#L..`.
* Eval matching normalises both sides: no scheme, `#fragment`, `?query` or trailing slash, and
  `github.com/<org>/<repo>/blob/<ref>/<path>` becomes `github.com/<org>/<repo>/<path>`.

## Findings that change the event-day design

Measured in this POC. Numbers are in `results/*.json` and in the table below.

1. **Extraction.** Docusaurus ships every tab panel in the static HTML, and tabs nest:
   the REST catalog page has 24 tab groups. A naive `select('[role=tabpanel]')` emits
   each nested panel twice and inflated that page from 122 KB to 342 KB of Markdown. Only
   take panels whose nearest `.tabs-container` is the current one. Heading ids are on
   `<h2 id=...>` with a zero-width-space hash link that has to be stripped. Code blocks
   use a custom `olake-code` wrapper with a filename title.
2. **Freshness signals.** olake.io is GitHub Pages behind Fastly. Every page has the same
   `Last-Modified` (the deploy time), and the ETag is `W/"<hex mtime>-<hex size>"`. A 304
   therefore only means "no deploy since", and after any deploy every page reports as
   changed. Sitemap `lastmod` is date-only, and 100 of 124 docs pages share one bulk date.
   Use a conditional GET on `sitemap.xml` as the cheap trigger, re-fetch all docs (about
   8 s), and diff the sha256 of the extracted Markdown to find the chunks that really
   changed. Re-embed only those.
3. **GitHub.** Without a token, conditional 304 requests still count against the limit
   of 60 per hour. With a token they cost nothing. `git ls-remote <repo> HEAD` takes
   0.7–1.0 s per repo and uses no REST quota, which makes it the simplest
   "did the repo move?" check.
4. **Corpus shape.** 13 of the 124 docs pages are stubs under 100 tokens (most of
   `/docs/fusion/*`). The single page `writers/iceberg/catalog/rest` is 30K tokens.
   olake-fusion is an Apache Amoro fork whose `docs/` folder is upstream Amoro text.
