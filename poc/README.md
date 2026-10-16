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
| 1 | Repos: shallow clones + allowlist (v2 = Tier A, the default; `--allowlist v1` for the first round) | `uv run python -I -m ingest.repos` | `$CACHE/corpus/repos.jsonl` |
| 1b | GitHub release notes (last 10 per repo, via `gh`) | `uv run python -I -m ingest.releases` | `$CACHE/corpus/releases.jsonl` |
| 1c | Docs manifest + diff (freshness baseline) | `uv run python -I -m ingest.manifest --out results/docs-manifest-<date>.json`; `uv run python -I -m ingest.diff_manifest OLD NEW` | `results/docs-manifest-2026-10-16.json` |
| 2 | Corpus stats | `uv run python -I -m ingest.stats` | `results/corpus.json` |
| 3 | Chunking at two target sizes (+ `--blog` writes the blog tier separately) | `uv run python -I -m chunking.chunker --target 300 --target 600 --blog` | `$CACHE/index/chunks-*.jsonl`, `results/chunks.json` |
| 4 | Retrieval benchmark | `uv run python -I -m retrieval.bench --target 300 --target 600 --dense BAAI/bge-small-en-v1.5 --dense BAAI/bge-base-en-v1.5 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --repeat 2` | `results/retrieval.json` |
| 4b | Query-time latency at capped onnx threads (2, 4, all) | `uv run python -I -m retrieval.latency --threads 2 --threads 4 --threads 0` | `results/latency_threads.json` |
| 4c | Retrieval bench on the canonical set (quality only, cached vectors) | `uv run python -I -m retrieval.bench --questions ../docs/eval-questions.md --target 300 --target 600 --dense BAAI/bge-small-en-v1.5 --dense BAAI/bge-base-en-v1.5 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --repeat 0 --reuse-embeddings --out results/retrieval-canonical.json` | `results/retrieval-canonical.json` (+ `retrieval-canonical-bge-reranker.json`) |
| 4d | Corpus v2 rerank / blog-tier table (canonical) | `uv run python -I -m retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --reuse-embeddings --out results/retrieval-v2.json` | `results/retrieval-v2.json` |
| 4e | Gate-signal comparison | `uv run python -I -m retrieval.gate_signals --questions ../docs/eval-questions.md` | `results/gate-signals.json` |
| 5 | Answer + abstain probe (hybrid bge-base + MiniLM rerank, 6 passages, JSON mode) | `uv run python -I -m answer.probe --think-probe --dense BAAI/bge-base-en-v1.5 --reranker Xenova/ms-marco-MiniLM-L-6-v2` | `results/answer.json` |
| 5b | Gate tuning without the LLM (retrieval + rerank only) | `uv run python -I -m answer.probe --no-generate --questions ../docs/eval-questions.md --dense BAAI/bge-base-en-v1.5 --out results/gate-canonical.json` | `results/gate-canonical.json` |
| 5c | Gate → one rewrite → decline sweep (no generation) | `uv run python -I -m answer.rewrite_probe --questions ../docs/eval-questions.md` | `results/gate-rewrite.json` |
| 6 | Scorer for any `/ask` URL (seed) | `uv run python -I -m eval.score --url http://127.0.0.1:8000/ask` | `results/eval_run.json` |
| 6b | Scorer on the canonical set | `uv run python -I -m eval.score --url http://127.0.0.1:8000/ask --questions ../docs/eval-questions.md --out results/eval_run-canonical.json` (add `--ids A,B,...` for a subset) | `results/eval_run-canonical.json`, `results/eval_run-canonical-v2-subset.json` |
| 7 | API + widget, served from two origins (env: `ASK_GATE_THRESHOLD`, `ASK_DENSE_MODEL`, `ASK_RERANKER`, `ASK_PROMPT_VERSION=v1\|v2`, `ASK_ONNX_THREADS`, `LLM_*`) | `ASK_GATE_THRESHOLD=-0.891 ASK_DENSE_MODEL=BAAI/bge-base-en-v1.5 uv run uvicorn api.app:app --host 127.0.0.1 --port 8000` and `uv run python -I -m http.server 8081 --bind 127.0.0.1 --directory api/demo` | open `http://127.0.0.1:8081/` (and `/csp.html` for the strict-CSP case); findings in `results/embed_probe.json` |
| 8 | Freshness probe | `uv run python -I -m freshness.probe` | `results/freshness.json` |

The eval harness reads either `eval/seed.jsonl` (the provisional 18 questions) or the
canonical table in `docs/eval-questions.md`; pass `--questions ../docs/eval-questions.md`.

## Repo allowlist (decided by inspection)

Round 2 default is **v2** (the research "Tier A", 38 files): olake READMEs, `protocol/root.go`,
`drivers/*/resources/spec.json` + `destination/{iceberg,parquet}/resources/spec.json` as Markdown field
tables; olake-ui README, `docker-compose-v1.yml`, `server/conf/app.yaml`; olake-helm READMEs,
UNINSTALL_GUIDE, `values.yaml`, `Chart.yaml`, `templates/NOTES.txt`; olake-fusion README, `CLAUDE.md`
sections 1–4 and the two Datazip-modified Amoro docs. The table below is **v1** (round 1, 84 files):

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

## Results

Generated from `results/*.json` by `uv run python -I -m common.results_table`. Rows tagged [seed] use the provisional seed set (`eval/seed.jsonl`: 18 questions, 14 with expected sources); treat differences under about 0.15 there as noise. Rows tagged [canonical] use the 94-row `docs/eval-questions.md` (82 rows with expected sources), and those are the numbers to cite. Hardware: Apple M5 Max (18 cores, 128 GB); the LLM is local ollama qwen3:32b Q4_K_M, so LLM latency is not representative of a hosted provider.

<!-- results-table:start -->
| Metric | Value | Command |
|---|---|---|
| Docs pages fetched / errors | 124 / 0 | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Docs fetch wall time (4 concurrent) | 7.52 s for 124 pages; extraction 3.49 s for all 209 pages; whole run incl. blog 16.64 s | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Docs HTML → Markdown | 11.2 MB → 1.11 MB | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Docs tokens (o200k) | 264,265 (p50 1,152/page, max 30,421) | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Docs code blocks / tables / tab groups / admonitions | 830 / 182 / 80 / 342 | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Docs stub pages (<100 tokens) | 13 | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Repo files kept (allowlist) / tokens | 38 / 80,176 | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Repo shallow clones wall time | 4.01 s (4 in parallel) | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Blog posts / tokens (optional, separate) | 85 / 446,275 | `ingest.docs --blog`, `ingest.repos`, `ingest.stats` |
| Chunks @ target 300 (hard max 450) | 1742 chunks; tokens p50 226, p95 420, max 501; 3 over hard max | `chunking.chunker --target 300` |
| Chunks @ target 600 (hard max 900) | 961 chunks; tokens p50 420, p95 796, max 891; 0 over hard max | `chunking.chunker --target 600` |
| Retrieval eval set (seed) | 14 questions with expected sources | `retrieval.bench` (see Steps) |
| BM25 index build @ 300 | 0.097 s for 1861 chunks | `retrieval.bench` (see Steps) |
| Embed bge-small-en-v1.5 @ 300 | 50 chunks 1.56 s; full 69.09 s (26.9 chunks/s); 79 chunks > 512 WordPiece tokens | `retrieval.bench` (see Steps) |
| Embed bge-base-en-v1.5 @ 300 | 50 chunks 4.36 s; full 229.79 s (8.1 chunks/s); 79 chunks > 512 WordPiece tokens | `retrieval.bench` (see Steps) |
| [seed] @300 bm25 | hit@1 0.286, hit@5 0.714, hit@10 0.857, MRR 0.451; latency p50 0.24 ms / p95 0.37 ms | `retrieval.bench` (see Steps) |
| [seed] @300 dense:BAAI/bge-small-en-v1.5 | hit@1 0.214, hit@5 0.714, hit@10 0.857, MRR 0.463; latency p50 5.12 ms / p95 6.45 ms | `retrieval.bench` (see Steps) |
| [seed] @300 dense:BAAI/bge-base-en-v1.5 | hit@1 0.357, hit@5 0.786, hit@10 0.929, MRR 0.567; latency p50 12.16 ms / p95 15.89 ms | `retrieval.bench` (see Steps) |
| [seed] @300 hybrid:BAAI/bge-small-en-v1.5 | hit@1 0.357, hit@5 0.714, hit@10 0.929, MRR 0.511; latency p50 5.79 ms / p95 7.75 ms | `retrieval.bench` (see Steps) |
| [seed] @300 hybrid:BAAI/bge-base-en-v1.5 | hit@1 0.429, hit@5 0.786, hit@10 0.857, MRR 0.581; latency p50 13.53 ms / p95 17.21 ms | `retrieval.bench` (see Steps) |
| [seed] @300 hybrid:BAAI/bge-small-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.357, hit@5 0.786, hit@10 0.857, MRR 0.545; latency p50 494.76 ms / p95 627.93 ms | `retrieval.bench` (see Steps) |
| [seed] @300 hybrid:BAAI/bge-small-en-v1.5+rerank:BAAI/bge-reranker-base | hit@1 0.429, hit@5 0.857, hit@10 0.857, MRR 0.61; latency p50 1945.55 ms / p95 2279.44 ms | `retrieval.bench` (see Steps) |
| [seed] @300 hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.429, hit@5 0.786, hit@10 0.929, MRR 0.59; latency p50 431.29 ms / p95 468.5 ms | `retrieval.bench` (see Steps) |
| [seed] @300 hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base | hit@1 0.429, hit@5 0.929, hit@10 0.929, MRR 0.645; latency p50 1786.92 ms / p95 2013.15 ms | `retrieval.bench` (see Steps) |
| [seed] @300 bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.429, hit@5 0.786, hit@10 0.786, MRR 0.574; latency p50 382.1 ms / p95 497.28 ms | `retrieval.bench` (see Steps) |
| [seed] @300 bm25+rerank:BAAI/bge-reranker-base | hit@1 0.357, hit@5 0.857, hit@10 0.857, MRR 0.55; latency p50 1624.89 ms / p95 1841.39 ms | `retrieval.bench` (see Steps) |
| BM25 index build @ 600 | 0.123 s for 951 chunks | `retrieval.bench` (see Steps) |
| Embed bge-small-en-v1.5 @ 600 | 50 chunks 3.15 s; full 44.05 s (21.6 chunks/s); 556 chunks > 512 WordPiece tokens | `retrieval.bench` (see Steps) |
| Embed bge-base-en-v1.5 @ 600 | 50 chunks 10.79 s; full 140.43 s (6.8 chunks/s); 556 chunks > 512 WordPiece tokens | `retrieval.bench` (see Steps) |
| [seed] @600 bm25 | hit@1 0.5, hit@5 0.857, hit@10 0.857, MRR 0.61; latency p50 0.25 ms / p95 0.33 ms | `retrieval.bench` (see Steps) |
| [seed] @600 dense:BAAI/bge-small-en-v1.5 | hit@1 0.286, hit@5 0.714, hit@10 0.857, MRR 0.485; latency p50 4.86 ms / p95 6.29 ms | `retrieval.bench` (see Steps) |
| [seed] @600 dense:BAAI/bge-base-en-v1.5 | hit@1 0.429, hit@5 0.714, hit@10 0.857, MRR 0.562; latency p50 11.76 ms / p95 15.52 ms | `retrieval.bench` (see Steps) |
| [seed] @600 hybrid:BAAI/bge-small-en-v1.5 | hit@1 0.357, hit@5 0.857, hit@10 0.857, MRR 0.54; latency p50 5.51 ms / p95 7.15 ms | `retrieval.bench` (see Steps) |
| [seed] @600 hybrid:BAAI/bge-base-en-v1.5 | hit@1 0.5, hit@5 0.786, hit@10 0.857, MRR 0.605; latency p50 12.15 ms / p95 15.84 ms | `retrieval.bench` (see Steps) |
| [seed] @600 hybrid:BAAI/bge-small-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.357, hit@5 0.714, hit@10 0.786, MRR 0.481; latency p50 407.02 ms / p95 427.94 ms | `retrieval.bench` (see Steps) |
| [seed] @600 hybrid:BAAI/bge-small-en-v1.5+rerank:BAAI/bge-reranker-base | hit@1 0.571, hit@5 0.714, hit@10 0.857, MRR 0.644; latency p50 1661.21 ms / p95 1778.08 ms | `retrieval.bench` (see Steps) |
| [seed] @600 hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.357, hit@5 0.643, hit@10 0.786, MRR 0.478; latency p50 432.7 ms / p95 476.34 ms | `retrieval.bench` (see Steps) |
| [seed] @600 hybrid:BAAI/bge-base-en-v1.5+rerank:BAAI/bge-reranker-base | hit@1 0.571, hit@5 0.714, hit@10 0.857, MRR 0.644; latency p50 1680.1 ms / p95 1950.47 ms | `retrieval.bench` (see Steps) |
| [seed] @600 bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.357, hit@5 0.643, hit@10 0.786, MRR 0.478; latency p50 402.27 ms / p95 407.45 ms | `retrieval.bench` (see Steps) |
| [seed] @600 bm25+rerank:BAAI/bge-reranker-base | hit@1 0.571, hit@5 0.714, hit@10 0.857, MRR 0.643; latency p50 1829.71 ms / p95 2014.23 ms | `retrieval.bench` (see Steps) |
| Bench process RSS (2 dense + 2 rerankers, after batch-embedding both corpora; not a serving number) | 8911.9 MB | `retrieval.bench` (see Steps) |
| Retrieval eval set (canonical) | 82 questions with expected sources | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| BM25 index build @ 300 | 0.086 s for 1861 chunks | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 bm25 | hit@1 0.549, hit@5 0.854, hit@10 0.915, MRR 0.68 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 dense:BAAI/bge-small-en-v1.5 | hit@1 0.585, hit@5 0.854, hit@10 0.89, MRR 0.692 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 dense:BAAI/bge-base-en-v1.5 | hit@1 0.598, hit@5 0.829, hit@10 0.902, MRR 0.702 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 hybrid:BAAI/bge-small-en-v1.5 | hit@1 0.634, hit@5 0.866, hit@10 0.939, MRR 0.736 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 hybrid:BAAI/bge-base-en-v1.5 | hit@1 0.646, hit@5 0.89, hit@10 0.927, MRR 0.745 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 hybrid:BAAI/bge-small-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.671, hit@5 0.829, hit@10 0.939, MRR 0.746 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.646, hit@5 0.854, hit@10 0.927, MRR 0.734 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @300 bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.659, hit@5 0.829, hit@10 0.927, MRR 0.742 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| BM25 index build @ 600 | 0.107 s for 951 chunks | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 bm25 | hit@1 0.5, hit@5 0.841, hit@10 0.902, MRR 0.647 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 dense:BAAI/bge-small-en-v1.5 | hit@1 0.537, hit@5 0.841, hit@10 0.878, MRR 0.646 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 dense:BAAI/bge-base-en-v1.5 | hit@1 0.561, hit@5 0.793, hit@10 0.878, MRR 0.668 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 hybrid:BAAI/bge-small-en-v1.5 | hit@1 0.585, hit@5 0.866, hit@10 0.939, MRR 0.719 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 hybrid:BAAI/bge-base-en-v1.5 | hit@1 0.598, hit@5 0.878, hit@10 0.939, MRR 0.727 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 hybrid:BAAI/bge-small-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.573, hit@5 0.829, hit@10 0.89, MRR 0.679 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 hybrid:BAAI/bge-base-en-v1.5+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.585, hit@5 0.841, hit@10 0.902, MRR 0.689 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical] @600 bm25+rerank:Xenova/ms-marco-MiniLM-L-6-v2 | hit@1 0.585, hit@5 0.805, hit@10 0.927, MRR 0.686 | `retrieval.bench` (see Steps) `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings` |
| [canonical, corpus v2] embed bge-small | 1742 chunks in 41.46 s (42.0 chunks/s) | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 bm25 | MRR 0.679, hit@1 0.549, hit@5 0.878, hit@6 0.878, hit@10 0.902; query p50 0.15 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 dense:bge-small | MRR 0.702, hit@1 0.585, hit@5 0.866, hit@6 0.89, hit@10 0.902; query p50 5.11 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small | MRR 0.744, hit@1 0.634, hit@5 0.878, hit@6 0.878, hit@10 0.939; query p50 9.08 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+rerank:TinyBERT-L-2-v2@10 | MRR 0.749, hit@1 0.634, hit@5 0.89, hit@6 0.915, hit@10 0.939; rerank p50 13.96 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+rerank:TinyBERT-L-2-v2@20 | MRR 0.778, hit@1 0.683, hit@5 0.902, hit@6 0.902, hit@10 0.939; rerank p50 28.14 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+rerank:MiniLM-L-6-v2@10 | MRR 0.731, hit@1 0.634, hit@5 0.866, hit@6 0.902, hit@10 0.939; rerank p50 150.82 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+rerank:MiniLM-L-6-v2@20 | MRR 0.742, hit@1 0.646, hit@5 0.841, hit@6 0.878, hit@10 0.939; rerank p50 339.68 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+rerank:BAAI/bge-reranker-base@10 | MRR 0.682, hit@1 0.549, hit@5 0.866, hit@6 0.878, hit@10 0.939; rerank p50 911.0 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+rerank:BAAI/bge-reranker-base@20 | MRR 0.649, hit@1 0.5, hit@5 0.866, hit@6 0.878, hit@10 0.915; rerank p50 1646.25 ms | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+blog@1.0 | MRR 0.63, hit@10 0.866; blog chunks in top 6: 2.28 | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical, corpus v2] @300 hybrid:bge-small+blog@0.5 | MRR 0.743, hit@10 0.939; blog chunks in top 6: 0.33 | `retrieval.bench --questions ../docs/eval-questions.md --target 300 --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --out results/retrieval-v2.json` |
| [canonical] gate signal bm25_max | recall 0.0 at 0 false abstains (threshold 2.716); AUC 0.863; p50 0.54 ms | `retrieval.gate_signals --questions ../docs/eval-questions.md` |
| [canonical] gate signal dense_max_cos | recall 0.583 at 0 false abstains (threshold 0.7126); AUC 0.861; p50 7.78 ms | `retrieval.gate_signals --questions ../docs/eval-questions.md` |
| [canonical] gate signal minilm_top@10 | recall 0.333 at 0 false abstains (threshold -6.3606); AUC 0.864; p50 141.15 ms | `retrieval.gate_signals --questions ../docs/eval-questions.md` |
| [canonical] gate signal minilm_top@20 | recall 0.333 at 0 false abstains (threshold -6.3606); AUC 0.864; p50 378.29 ms | `retrieval.gate_signals --questions ../docs/eval-questions.md` |
| [canonical] gate signal tinybert_top@10 | recall 0.417 at 0 false abstains (threshold 0.0137); AUC 0.883; p50 13.04 ms | `retrieval.gate_signals --questions ../docs/eval-questions.md` |
| [canonical] gate signal tinybert_top@20 | recall 0.333 at 0 false abstains (threshold 0.0153); AUC 0.878; p50 31.93 ms | `retrieval.gate_signals --questions ../docs/eval-questions.md` |
| [canonical] rewrite cost (local qwen3:32b, reasoning off) | p50 1174.8 ms, p95 1817.8 ms; 191.7 prompt + 11.9 completion tokens; NONE on 4 must-abstain / 0 must-answer rows | `answer.rewrite_probe --questions ../docs/eval-questions.md` |
| [canonical] gate dense_max_cos < 0.71 → one rewrite → decline | rewrite fires 7/94; recall 0.5; false declines 0 []; gate alone: recall 0.583, false declines 0 | `answer.rewrite_probe --questions ../docs/eval-questions.md` |
| [canonical] gate tinybert_top@10 < 0.3 → one rewrite → decline | rewrite fires 11/94; recall 0.583; false declines 1 ['ADV-02']; gate alone: recall 0.667, false declines 3 | `answer.rewrite_probe --questions ../docs/eval-questions.md` |
| Query-time latency, onnx threads=2 | query_embed_bge_small p50 5.4; query_embed_bge_base p50 15.8; rerank_ms-marco-MiniLM-L-6-v2_top10 p50 205.9; rerank_ms-marco-MiniLM-L-6-v2_top20 p50 546.4; rerank_ms-marco-MiniLM-L-6-v2_top20_trunc1000chars p50 358.2; rerank_bge-reranker-base_top10 p50 922.3; rerank_bge-reranker-base_top20 p50 2119.7 | `retrieval.latency` |
| Query-time latency, onnx threads=4 | query_embed_bge_small p50 3.9; query_embed_bge_base p50 10.3; rerank_ms-marco-MiniLM-L-6-v2_top10 p50 122.4; rerank_ms-marco-MiniLM-L-6-v2_top20 p50 331.2; rerank_ms-marco-MiniLM-L-6-v2_top20_trunc1000chars p50 207.3; rerank_bge-reranker-base_top10 p50 547.3; rerank_bge-reranker-base_top20 p50 1356.1 | `retrieval.latency` |
| Query-time latency, onnx threads=default(all cores) | query_embed_bge_small p50 3.8; query_embed_bge_base p50 9.6; rerank_ms-marco-MiniLM-L-6-v2_top10 p50 117.0; rerank_ms-marco-MiniLM-L-6-v2_top20 p50 287.2; rerank_ms-marco-MiniLM-L-6-v2_top20_trunc1000chars p50 186.0; rerank_bge-reranker-base_top10 p50 568.4; rerank_bge-reranker-base_top20 p50 1475.2 | `retrieval.latency` |
| Abstain policy_a_gate (threshold -0.891) | precision 1.0, recall 1.0, false-abstain 0.0 | `answer.probe` |
| Abstain policy_b_model | precision 0.75, recall 1.0, false-abstain 0.071 | `answer.probe` |
| Abstain policy_a_or_b | precision 0.75, recall 1.0, false-abstain 0.071 | `answer.probe` |
| Answer latency retrieval_ms | p50 13.7 / p95 21.6 ms | `answer.probe` |
| Answer latency rerank_ms | p50 331.9 / p95 523.5 ms | `answer.probe` |
| Answer latency llm_ttft_ms | p50 8391.9 / p95 10530.1 ms | `answer.probe` |
| Answer latency llm_total_ms | p50 16974.2 / p95 24014.9 ms | `answer.probe` |
| Answer latency total_ms | p50 17375.0 / p95 24365.4 ms | `answer.probe` |
| Tokens per answer (prompt / completion, mean) | 1858.1 / 71.8 | `answer.probe` |
| Answered questions citing an expected source | 0.714 | `answer.probe` |
| [canonical] MiniLM gate threshold 1.177 | abstain recall 0.92 (unanswerable+out-of-scope), false-abstain 0.130 (answerable) | `answer.probe --no-generate --questions ../docs/eval-questions.md` |
| [canonical] MiniLM gate threshold -0.891 | abstain recall 0.50 (unanswerable+out-of-scope), false-abstain 0.043 (answerable) | `answer.probe --no-generate --questions ../docs/eval-questions.md` |
| [canonical] MiniLM gate threshold -4.0 | abstain recall 0.50 (unanswerable+out-of-scope), false-abstain 0.000 (answerable) | `answer.probe --no-generate --questions ../docs/eval-questions.md` |
| [canonical] expected source in top-6 passages | 0.854 | `answer.probe --no-generate --questions ../docs/eval-questions.md` |
| [canonical] /ask: schema valid / source hit / behaviour correct | 1.0 / 0.695 / 0.84 | `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical.json` |
| [canonical] /ask: abstain recall / false-abstain (answerable) | 0.833 / 0.072 | `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical.json` |
| [canonical] judge fact coverage / BEHAVIOR pass / contradictions | 0.573 / 0.75 / 4 | `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical.json` |
| [canonical] /ask latency p50 / p95 (local qwen3:32b, concurrency 4) | 105319.7 / 147428.2 ms | `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical.json` |
| [canonical] full run wall time | 2646.5 s (2201.9 s asks + 444.5 s judge) | `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical.json` |
| [canonical] combined policy /ask: schema / behaviour / source hit | 1.0 / 0.936 / 0.841 | API with `ASK_RERANKER=none ASK_GATE_SIGNAL=tinybert ASK_GATE_THRESHOLD=0.3 ASK_REWRITE=1 ASK_MAX_PASSAGES=10 ASK_PROMPT_VERSION=v3` + `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical-combined.json` |
| [canonical] combined policy: abstain recall (12) / false abstain answerable / all must-answer | 0.833 / 0.043 / 0.049 | API with `ASK_RERANKER=none ASK_GATE_SIGNAL=tinybert ASK_GATE_THRESHOLD=0.3 ASK_REWRITE=1 ASK_MAX_PASSAGES=10 ASK_PROMPT_VERSION=v3` + `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical-combined.json` |
| [canonical] combined policy: fact coverage / BEHAVIOR pass / contradictions | 0.603 / 0.85 / 4 | API with `ASK_RERANKER=none ASK_GATE_SIGNAL=tinybert ASK_GATE_THRESHOLD=0.3 ASK_REWRITE=1 ASK_MAX_PASSAGES=10 ASK_PROMPT_VERSION=v3` + `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical-combined.json` |
| [canonical] combined policy: server reasons; rewrite fired | {'answered': 80, 'unparseable': 2, 'model_unanswerable': 4, 'gate_after_rewrite': 8}; 11 | API with `ASK_RERANKER=none ASK_GATE_SIGNAL=tinybert ASK_GATE_THRESHOLD=0.3 ASK_REWRITE=1 ASK_MAX_PASSAGES=10 ASK_PROMPT_VERSION=v3` + `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical-combined.json` |
| [canonical] combined policy: latency p50 / p95; wall | 25707.5 / 48500.2 ms; 2984.9 s | API with `ASK_RERANKER=none ASK_GATE_SIGNAL=tinybert ASK_GATE_THRESHOLD=0.3 ASK_REWRITE=1 ASK_MAX_PASSAGES=10 ASK_PROMPT_VERSION=v3` + `eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical-combined.json` |
| [canonical A/B subset, 35 rows] prompt v1 | behaviour correct 23/35; fact coverage 0.533; BEHAVIOR pass 15/20 | `ASK_PROMPT_VERSION=v2` API + `eval.score --ids <25 non-answerable + 10 answerable>` |
| [canonical A/B subset, 35 rows] prompt v2 | behaviour correct 26/35; fact coverage 0.536; BEHAVIOR pass 16/20 | `ASK_PROMPT_VERSION=v2` API + `eval.score --ids <25 non-answerable + 10 answerable>` |
| [seed] Scorer: schema valid / source hit / behaviour correct | 1.0 / 0.714 / 0.944 | `eval.score` |
| Scorer: judge fact coverage (mean) | 0.817 | `eval.score` |
| Scorer: /ask latency p50 / p95 | 34902.0 / 54839.8 ms | `eval.score` |
| Scorer: full run wall time | 195.9 s (156.8 s asks + 39.1 s judge) | `eval.score` |
| Cross-origin widget: gated answer / LLM answer | 911 ms / 10304 ms (preflight then POST; preflight cached afterwards) | `api.app` + `http.server` on a second origin, driven in Chrome |
| Strict host CSP (connect-src 'self') | widget renders, /ask blocked: connect-src violation | `api.app` + `http.server` on a second origin, driven in Chrome |
| API RSS (bge-base + MiniLM + BM25) | 1419 MB after 1 query, 2609 MB after concurrency-4 run; startup 0.4 s | `api.app` + `http.server` on a second origin, driven in Chrome |
| olake.io conditional GET | If-None-Match → 304 in 12.0 ms; ETag = deploy mtime + size | `freshness.probe` |
| GitHub 304 counts against rate limit? | unauthenticated: yes (3 used for 3); token: no | `freshness.probe` |
| git ls-remote HEAD check | 714-1005 ms per repo, no API quota | `freshness.probe` |
<!-- results-table:end -->

## Round 2: corpus v2, rerank / gate decision tables, combined abstain policy

**Corpus v2** (`ingest.repos` defaults to allowlist v2; `ingest.releases`; `chunking.chunker --blog`):
* **Tab-safe chunks.** html2md wraps every tab group in invisible `<!-- tabs:start/end -->`
  markers, and the chunker keeps a tab stack. No chunk spans two tab panels, and each
  chunk header carries the full label path, e.g.
  `REST Catalog › Tab: Nessie › Configuration › Authentication › Tab: Token › Tab: OLake UI`.
  Without the markers, the nested catalog → auth → UI/CLI groups on the REST page were
  mislabelled.
* **Repo allowlist v2** (the research "Tier A", 38 files, 80K tokens):
  * connector `spec.json` files converted to Markdown field tables (`ingest/spec2md.py`,
    which handles `oneOf`, `allOf` if/then and `dependencies`; the Iceberg spec gives
    118 rows);
  * olake-fusion `CLAUDE.md` sections 1–4 only, with other lines blanked so line anchors
    stay valid;
  * helm `NOTES.txt`;
  * the two Datazip-modified Amoro docs;
  * the stale root `docker-compose.yml` of olake is dropped.
* **Release notes:** the last 10 GitHub releases per repo, 34 notes and 8.6K tokens, cited
  as `releases/tag/<tag>`. olake v0.12.1 is newer than anything in the docs.
* **Blog:** a separate tier file (`chunks-300-blogtier.jsonl`).
* **Fusion docs coverage:** 23 pages, 7 stubs under 100 tokens, 28.4K content tokens, of
  which `getting-started/compaction` alone is 10.3K.

**Rerank** (canonical, 82 rows, hybrid bge-small, 300-token chunks):
* None: MRR 0.744, hit@10 0.939.
* FlashRank TinyBERT: top 10 0.749 (14 ms), top 20 0.778 (28 ms, +53 MB RAM).
* MiniLM-L6: top 10 0.731 (151 ms), top 20 0.742 (340 ms).
* bge-reranker-base: top 10 0.682 (0.9 s), top 20 0.649 (1.6 s).

Only the 4 MB TinyBERT helps. The gain is inside noise for 82 rows but nearly free.

**Blog tier A/B:**
* At weight 1.0, MRR falls to 0.630 and hit@10 to 0.866; blog chunks fill 2.3 of the top
  6 slots.
* At weight 0.5 it is neutral (0.743).
* Keep the blog out, or at most a ≤0.5-weight fallback.

**Gate signals** (12 must-abstain vs 82 must-answer rows), recall at 0 false abstains:

| Signal | Recall | AUC | Cost |
|---|---|---|---|
| Max dense cosine | 0.58 | 0.861 | free with retrieval |
| TinyBERT top 10 | 0.42 | 0.883 | 13 ms |
| MiniLM top 10 | 0.33 | 0.864 | 141 ms |
| Max BM25 | 0.00 | 0.863 | <1 ms |

Every zero-false-abstain threshold sits exactly on the lowest must-answer score, so none
has any margin.

**Gate → one rewrite → decline** (`answer.rewrite_probe`; no generation):
* **Rewrite cost:** p50 1.17 s locally, about 192 prompt and 12 completion tokens.
* **`NONE` output:** fired on 4 out-of-scope rows and on 0 must-answer rows.
* **Dense cosine below 0.71:** the rewrite fires on 7/94 rows; recall 0.50 with 0 false
  declines. The gate alone does slightly better (0.58, 0), because the rewrite also
  rescues an unanswerable row.
* **TinyBERT below 0.3:** the rewrite fires on 11/94 rows; recall 0.58 with 1 false
  decline (ADV-02). The gate alone gets 0.67 recall with 3 false declines; the rewrite
  rescues SET-07 and SYNC-09.
* **The rewrite call is itself injectable.** For ADV-01 and ADV-02 it produced the injected
  claim or a refusal instead of keywords. Only retrieval sees it, but constrain it:
  keywords only, no sentences, length cap.
* **Net:** the gate stage reaches about 50–60% recall. The rest of the abstaining must come
  from the model.

**Runaway generation (production lesson).**
* With JSON mode and no `max_tokens`, one qwen3 request kept generating past 6,000 tokens
  at 8 tok/s and held ollama's single slot.
* At concurrency 4 the queue then cascaded: client timeouts at 180 s and 300 s,
  abandoned requests still occupying the slot.
* The pipeline now caps generation (`ASK_MAX_TOKENS`, default 600) and uses a shorter LLM
  timeout (`ASK_LLM_TIMEOUT`).
* On the event box, also bound in-flight LLM calls with a semaphore and return
  503 + `Retry-After` instead of queueing without limit.

**Docs manifest and re-crawl.**
* `results/docs-manifest-2026-10-16.json` is the baseline, with extractor commit 20b4bac.
  `ingest.diff_manifest OLD NEW` lists the added, removed and changed pages.
* Morning re-crawl into a fresh cache (tested: 9.8 s, 0 changes):

```bash
cd poc && export ASK_OLAKE_CACHE="$HOME/ask-olake-cache-$(date +%Y%m%d-%H%M)" && uv run python -I -m ingest.docs && uv run python -I -m ingest.manifest --out "results/docs-manifest-$(date +%F).json" && uv run python -I -m ingest.diff_manifest results/docs-manifest-2026-10-16.json "results/docs-manifest-$(date +%F).json"
```

**Combined policy, end to end** (`results/eval_run-canonical-combined.json`, 94 rows; config stored in the file).

Config:
* hybrid bge-small, no ranking reranker, k = 10 passages;
* TinyBERT@10 gate below 0.3, then one rewrite, decline if `NONE` or still below;
* prompt v3, qwen3:32b with reasoning off, `max_tokens` 600.

Results (v1 run in parentheses):
* schema valid 1.0;
* behaviour correct **0.936** (0.84);
* source hit **0.841** (0.695);
* judged fact coverage 0.603 (0.573);
* judged BEHAVIOR pass 0.85 (0.75);
* 4 contradictions; 0 5xx.

Abstaining:
* **Recall on the 12 must-abstain rows: 0.833** (target ≥ 0.90). 7 were declined after the
  rewrite and 3 by the model. UNK-02 and UNK-04 were answered from loosely related pages.
* **False abstains on the 82 must-answer rows: 4 (4.9%)**, of which 3 of 69 answerable (4.3%):
  * SRC-03 and SYNC-03: unparseable JSON, one of them truncated at the cap;
  * SYNC-12: the model returned `answerable=false`;
  * ADV-02: declined after the injectable rewrite.
* By type: negative 5/5 (2/5), false-premise 4/4 answered but judged BEHAVIOR only 2/4,
  adversarial 3/4.

Cost and timing:
* The rewrite fired on 11/94 rows (11.7%): p50 1.27 s, about 196 tokens.
* Generation: 3,294 prompt and 167 completion tokens on average; 1 answer hit the cap.
* Local LLM p50 26 s (TTFT 13 s). The whole run took 2,985 s at concurrency 1.

## Canonical end-to-end run: exact config and abstain breakdown

`results/eval_run-canonical.json` (94 rows) was produced by this config (also stored in the file under `config`):

| Setting | Value |
|---|---|
| Chunks | `chunks-300`: docs + repo allowlist v1, no blog |
| Retrieval | hybrid RRF k=60 over BM25 top 50 + dense top 50 |
| Embedder | BAAI/bge-base-en-v1.5 (fastembed int8 ONNX) with the BGE query prefix |
| Reranker / gate model | Xenova/ms-marco-MiniLM-L-6-v2 over the fused top 20; also the gate signal |
| Gate | abstain without calling the LLM if top MiniLM score < −0.891 (tuned on the 18-question seed set) |
| Passages to LLM | k = 6 |
| LLM | qwen3:32b Q4_K_M, ollama 0.33.3 OpenAI-compatible API, temperature 0, JSON mode, `reasoning_effort="none"`, prompt v1 |
| Model abstain rules | `answerable=false` → abstain; no valid `[n]` citation → abstain; unparseable JSON → abstain |
| Scorer | concurrency 4, timeout 180 s; judge qwen3:32b with reasoning off, judge concurrency 2 |
| Abstain detection | `sources` empty, or the don't-know regex anywhere in the answer |

False abstains on all 82 must-answer rows: **13**.
* **gate (7):** SET-07, SRC-11, SYNC-09, DEP-06, FP-03, ADV-02, ADV-03.
* **model `answerable=false` (5):** SRC-08, SRC-09, SYNC-12, FP-02, FP-04.
* **scorer's abstain regex on a sourced answer (1):** SRC-16.
* **no valid citation:** 0.
* **answerable rows only (5 of 69):** SRC-11, SYNC-09 and DEP-06 by the gate; SRC-09 and SYNC-12 by the model.

Missed abstains: **2 of 12**, UNK-04 (top score 0.88) and OOS-03 (0.78). Both passed the gate, and the model answered from loosely related passages.

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
5. **CPU cost lives in embedding and reranking, not in BM25 or vector search.** All
   numbers are fastembed int8 ONNX on an M5 Max (CoreML was no faster).
   * Indexing throughput: bge-small 27 chunks/s and bge-base 8 chunks/s. The 1,861-chunk
     corpus takes 69 s and 230 s. A small cloud VM will be several times slower, so embed
     offline and ship the vectors.
   * Rerank at 2 threads: MiniLM-L6 takes 206 ms for the top 10 and 546 ms for the top 20.
     bge-reranker-base takes 0.9 s and 2.1 s.
   * Query embedding takes 4–16 ms, BM25 under 1 ms, and BM25 index build 0.1 s.
6. **Chunk size vs the 512-token embedder limit.** At target 600, 58% of chunks exceed
   bge's 512 WordPiece tokens and are silently truncated. At target 300 it is 4%.
   WordPiece counts run about 1.17x o200k at the median (275 vs 235 at target 300,
   554 vs 470 at 600). Keep chunks around 300 o200k tokens for BERT-family embedders and
   rerankers.
7. **Retrieval quality.** On the canonical set (82 rows with sources, 300-token chunks),
   MRR@10 (hit@10):

   | Config | MRR@10 (hit@10) |
   |---|---|
   | BM25 | 0.680 |
   | Dense bge-small | 0.692 |
   | Dense bge-base | 0.702 |
   | Hybrid RRF, bge-small | 0.736 (0.94) |
   | Hybrid RRF, bge-base | 0.745 (0.93) |

   * Hybrid is the clear winner, and bge-small is nearly as good as bge-base at 3.3x less
     embedding cost.
   * At 600 tokens every config scores lower (hybrid 0.72–0.73).
   * Cross-encoders do not pay off. MiniLM-L6 is neutral at 300 tokens (+0.01 / −0.01)
     and hurts at 600 (−0.04). bge-reranker-base hurts at 300 (0.664 vs 0.736) and costs
     1–2 s per query.
   * The seed set (14 rows) had suggested the opposite. Its gains were noise, so don't
     trust small eval sets for this decision.
   * Identifier questions (CLI flags, config keys defined only in Go) are where dense
     retrieval fails and BM25 rescues them. An exact-match boost for `--flags` and
     `snake_case` keys found in the question is a cheap next step.
8. **LLM control (ollama 0.33.3, qwen3:32b, OpenAI-compatible API).** Only
   `reasoning_effort="none"` disables thinking. `/no_think` in the prompt and
   `extra_body={"think": false}` are ignored and cost 2–4x latency. JSON mode
   (`response_format: json_object`) parsed on 18/18 questions. Locally the model runs at
   about 220 tok/s prefill and 10 tok/s decode, so local latency (about 17 s per answer)
   says nothing about the event provider. Per-answer tokens are what carry over: about
   1.86K prompt and 72 completion tokens.
9. **Abstaining. The reranker-score gate does not generalise.**
   * On the 18-question seed set, a MiniLM top-score threshold of −0.89 separated the
     cases perfectly.
   * On the 94-row canonical set that threshold catches only 50% of unanswerable and
     out-of-scope rows, and false-abstains on 4.3% of answerable rows.
   * The best canonical threshold, 1.18, reaches 92% recall but false-abstains on 13% of
     answerable rows.
   * Two things break it. Near-domain unanswerables score high (UNK-01: 6.3).
     Injection-wrapped questions score very low (ADV-03: −6.4), because the injected
     text dominates the query.
   * Use the gate only as a cheap off-topic short-circuit near −4 (0% false abstains on
     answerable rows, about 0.3 s, no LLM call). Let the model's `answerable` flag and
     citation validation do the real abstaining.
   * End to end on the canonical set with the v1 prompt, the model policy plus the −0.89
     gate gives abstain recall 0.83 and false-abstain 0.072 on answerable rows, against a
     target of ≤0.05.
   * Behaviour by row type: false-premise 1/4, negative 2/5, adversarial 2/4. The v1
     prompt treats "the premise is wrong" as "not covered" and abstains. The v2 prompt
     (`ASK_PROMPT_VERSION=v2`) targets exactly that; A/B results are below.
9b. **Prompt v2 A/B** (same retrieval and gate; 35 canonical rows: all 25 non-answerable
    plus 10 answerable):
    * Behaviour correct goes from 23/35 to 26/35: false-premise 1 → 2, negative 2 → 3,
      answerable 8 → 9.
    * The judged false-premise BEHAVIOR check goes from 2/4 to 3/4. Fact coverage is flat
      (0.54 on the subset).
    * Unanswerable stays at 5/6 net: UNK-04 improved and UNK-02 regressed into a partial
      answer.
    * One v2 answer (FP-02) accepted a false premise ("trigger compaction via
      Configure"). The deterministic behaviour rule only checks "did not abstain", so for
      false-premise rows trust the judged BEHAVIOR check.
    * Direction is right, but it needs few-shot examples of premise corrections and a rule
      that a correction must cite the passage contradicting the premise. n = 4–6 per type
      is small.
10. **Citations.** The model's `[n]` refers to passage numbers. The `/ask` contract
    returns deduplicated `sources`, so the markers must be renumbered to positions in
    `sources` or the widget's links point at the wrong URL. When several sections are
    packed into one chunk, the chunk's anchor is its first section, which is sometimes not
    the cited sentence. The OLake docs repeat content (install, getting-started and
    fusion/install), so eval rows need several acceptable sources.
11. **Embedding.** One script tag plus a shadow DOM widget works cross-origin: preflight,
    then POST; the preflight is cached afterwards. Chromium documents a 2 h cap on that
    cache whatever `max-age` says; I didn't measure it. Host styles do not leak in. A strict host CSP (`connect-src 'self'`)
    lets the widget render but blocks `/ask`, and `fetch` reports CSP and CORS failures
    identically. Document the `connect-src` and `script-src` additions, and offer an
    iframe embed as the fallback. FastAPI rejects `text/plain` bodies, so a
    preflight-free simple request is not available without relaxing that check. The
    contract keeps `{answer, sources}` even on 422 and 503. RSS grows with concurrent
    reranks (1.4 GB to 2.6 GB at concurrency 4).

## Event-day pipeline these numbers point to

* **Ingest.** Sitemap → `/docs/` pages → Markdown with this extractor's rules: nested
  tabs with group markers, anchors, code language. Add allowlist v2 (Tier A) pinned to
  SHAs, plus the last 10 GitHub release notes per repo. Keep the blog out of the index:
  at weight 1.0 it costs 0.11 MRR. At most add it as a ≤0.5-weight fallback.
* **Chunks.** About 300 o200k tokens with a `Page › Section › Tab` header. Never span two
  tabs. YAML/JSON split by keys, Go by declarations, spec.json as field tables.
  Citations go to page#anchor and to GitHub permalinks with `?plain=1#Lx-Ly`.
* **Index.** BM25 plus bge-small, fused with RRF (k=60): canonical MRR 0.744, hit@10
  0.939. Embed offline on the laptop (42 chunks/s) and ship the 2.6 MB of vectors with the
  deploy.
* **Rerank.** None in the ranking path is the lead's decision. FlashRank TinyBERT@20 is
  the one candidate worth revisiting: +0.034 MRR for 28 ms and about 53 MB. MiniLM and
  bge-reranker-base lose quality here.
* **Off-topic gate.** Max dense cosine is free and reaches 0.58 recall at 0 false
  abstains. TinyBERT top-10 has the best AUC (0.883) for 13 ms. The threshold has no
  margin, so pair it with the one-rewrite safety net:
  * use the hardened rewrite (v2): keywords only, plus the sanitizer;
  * decline only if the gate still fires after the rewrite;
  * expect the gate stage to catch only about 50–60% of must-abstain rows.
* **Generate.** Use the provider with reasoning off, JSON mode and k=10 passages (about
  3.5–4K prompt tokens). Always cap `max_tokens`. Bound in-flight LLM calls with a
  semaphore and return 503 + `Retry-After` beyond it. Keep the LLM timeout below the
  client timeout. The model's `answerable` flag plus "no valid citation → abstain" do the
  rest of the abstaining. Prompt v3 corrects false premises and answers support questions
  with the supported list.
* **Contract.** Always `{answer, sources}`, including on 4xx and 5xx. Renumber `[n]` to
  positions in `sources`. Debug detail goes in response headers (`X-Ask-*`), never in the
  body.
* **Freshness.** Run the 07:30 re-crawl one-liner above, then `ingest.diff_manifest`.
  Re-chunk and re-embed only changed pages. Use `git ls-remote` for the repos and
  `gh api .../releases` for release notes.
* **Eval.** Retrieval-only checks take minutes (`retrieval.bench --repeat 0
  --reuse-embeddings`). End-to-end runs need the provider: with a local single-slot 32B
  model, 94 rows take 45+ minutes. Use the strongest model available as judge.
* **Serving box.** Cap onnxruntime threads (`ASK_ONNX_THREADS`). Serving RSS is about
  0.25 GB for BM25 + bge-small; TinyBERT adds about 53 MB.
