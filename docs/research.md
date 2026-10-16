# Ask OLake: research, comparisons and decisions

Status: draft, filled in as the research reports and POC measurements land. `PENDING(x)` marks a section or number that
waits on input x. Measured numbers name their source file, and unmeasured goals are labelled **target**.
The runbook that carries out these decisions is [plan.md](plan.md). Open items are in [open-questions.md](open-questions.md).

## 1. Executive summary

1. **Deliverable**: a public `POST /ask` (`{"question"}` in, `{"answer", "sources"}` out), an embeddable chat UI, and a repo
   with a README on architecture and design choices ([challenges page][ch]).
2. **Corpus**: all 124 `/docs/` pages from the rendered HTML, including release notes; the 4 datazip-inc repos through a file
   allowlist; blog posts as a lower tier (decision D4); no issues or discussions in v1 (§3).
3. **Citations**: `sources` holds canonical sitemap URLs (trailing slash, no anchor) and branch-form GitHub blob URLs.
   Deep links with anchors or line ranges appear only in the UI (§3.4).
4. **Architecture**: hybrid retrieval (BM25 plus local dense embeddings, RRF k=60), a local cross-encoder rerank, then one
   grounded LLM call with `[n]` citations, behind two gates and three logged abstain triggers. The fallback is BM25-only
   with the same chunks and prompt, behind a config flag (§4).
5. **Stack**: Python 3.12, FastAPI, the `openai` SDK pointed at any OpenAI-compatible endpoint, fastembed (ONNX, CPU) for
   embeddings and reranking, bm25s, and numpy brute-force vectors. One container. PENDING(stack report: host, model, prices) (§5).
6. **Widget**: a small `widget.js` loader that injects a launcher and an iframe served from our origin (`/embed`), plus a plain
   iframe snippet and a Docusaurus `scripts` snippet (§5.6).
7. **Freshness**: incremental rebuilds keyed on sitemap `lastmod` plus content hash and `git ls-remote` SHAs. HTTP
   ETags on olake.io change on every site deploy, so they cannot detect per-page changes (§3.5).
8. **Evaluation**: a 6-column Markdown question table scored by deterministic checks plus an LLM judge, run against the
   deployed URL at every checkpoint (§6).
9. **Biggest risks**: credits or the endpoint failing during post-freeze scoring, a source-matching rule that differs from
   ours, and over- or under-abstaining (§8).

## 2. Event and challenge (verified)

The doc-writer opened both pages on 2026-10-16. The lead verified them on the same day.

| Item | Fact | Source |
|---|---|---|
| Date and place | Sunday 2026-10-18, 10:00-17:30 IST, at the OLake office, HustleHub H203, 24th Main Rd, Sector 2, HSR Layout, Bengaluru | [event page][ev] |
| Format | In person, individual entries only | [event page][ev] |
| Schedule | 10:00-10:30 check-in, kickoff and problem briefing; 10:30 hacking starts; 14:30 code freeze ("submit your endpoint and repo"); 14:30-15:30 lunch; 15:30 top 10 announced; 15:45-17:00 finalist demos; 17:00-17:30 results and prizes | [event page][ev] |
| Bring | Laptop and charger, a government photo ID (needed for venue entry), a GitHub account | [event page][ev] |
| Provided | LLM API credits (provider and amount not stated), Wi-Fi, food | [event page][ev], [challenges page][ch] |
| Challenge | A chat assistant over OLake docs for both products: OLake ingestion (Postgres, MySQL, MongoDB, Oracle, MSSQL, DB2, Kafka and S3 into Iceberg or Parquet) and OLake Fusion (Iceberg table maintenance such as compaction). Topics: setup, source configuration, sync modes, catalogs, table maintenance, deployment, troubleshooting | [challenges page][ch] |
| Knowledge sources | The OLake docs; the repos olake, olake-ui, olake-helm and olake-fusion; outside sources when the docs fall short | [challenges page][ch] |
| Behaviour | Every answer cites its sources and says clearly when it does not know. "Build it as if it's going to production" | [challenges page][ch] |
| Deliverables | `POST /ask` taking `{"question": "..."}` and returning `{"answer": "...", "sources": ["<url>", ...]}`; a chat UI embeddable in a docs site; a repo with a README on architecture and design choices | [challenges page][ch] |
| Judging (100) | Answer accuracy 35; citations and honesty 15; production readiness 20; UX and easy embedding 15; engineering (freshness, latency, cost) 15. All entries are scored on the same test set after the code freeze. The top 10 then present live | [challenges page][ch] |
| Judges | Sachin Garg (Tech Lead, Airbnb) and Brihati Jain (Co-Founder, Conqur AI) | [challenges page][ch] |
| Side prizes | "Best Use of Gemma 4" (Google DeepMind; Gemma 4 through the Gemini API). "Best Open-Source AI Project" (DigitalOcean): meaningful use of open-source or open-weight AI, a public GitHub repo under an open-source license; a harness entry must be new or significantly changed. Its reward is a DEV badge plus an MLH swag bag | [challenges page][ch] |
| Not specified | Latency or timeout limits, scorer concurrency, how sources are matched, the "don't know" format, submission mechanics, whether the endpoint must stay up after the freeze, test-set size and grading method, and a pre-existing-code policy for Ask OLake | [event page][ev], [challenges page][ch]; listed as K1-K14 in [open-questions.md](open-questions.md) |

Implication (inference, not stated anywhere): scoring runs after 14:30 and before the 15:30 top-10 announcement, against
the live endpoint. So the service must stay up, warm and rate-limit-tolerant in that window and through the demos until 17:00.

## 3. Corpus

### 3.1 Docs site

| Measurement | Value | Source |
|---|---|---|
| Sitemap URLs | 275 in total: 124 under `/docs/`, 86 under `/blog/` (85 posts plus the `/blog/` index), 65 others (community, company pages). 231 carry `lastmod`. All 275 end with `/` | The doc-writer fetched [the sitemap][sitemap] at 2026-10-16T17:14Z and counted `<loc>` by path prefix. It matches `poc/results/corpus.json` (`sitemap_urls`: 275) |
| Release notes | 24 pages under `/docs/release/` plus 2 under `/docs/fusion/release/` | Same sitemap count. `poc/results/corpus.json` (`by_section`) |
| Docs size | 124 pages, 263,614 tokens (o200k_base), 830 code blocks, 182 tables, 80 tab groups, 342 admonitions. The median page has 1,152 tokens, the largest 30,229 (`/docs/writers/iceberg/catalog/rest/`). 13 pages have under 100 tokens | `poc/results/corpus.json` |
| Blog size | 85 posts, 446,137 tokens. The median post has 4,175 tokens | `poc/results/corpus.json` |
| Fetch cost | 209 pages (docs plus blog) fetched in 12.77 s at concurrency 4, with a per-page p50 of 0.243 s. HTML-to-Markdown extraction took 3.49 s | `poc/results/corpus.json` |
| Hosting | olake.io answers with `server: GitHub.com` and `cache-control: max-age=600` | `poc/results/freshness.json` |

Decision: ingest the **rendered HTML** of every `/docs/` page and extract the article to Markdown, keeping heading anchors,
code fences, tables and tabs. Reasons: (1) the sitemap URL is the canonical citation URL as is, so no path-to-slug
mapping is needed; (2) MDX imports, partials and components can hide content from a raw-source reader;
(3) the whole fetch is cheap (12.77 s above). PENDING(docs-site report: the article selector, whether `llms.txt` or
`llms-full.txt` exists and how complete it is, and any page that renders client-side only).

### 3.2 Repositories

| Repo | Branch (as cloned) | Tracked files | Allowlisted files | Tokens | Source |
|---|---|---|---|---|---|
| olake | master | 450 | 58 | 82,666 | `poc/results/corpus.json` |
| olake-ui | master | 519 | 11 | 22,682 | `poc/results/corpus.json` |
| olake-helm | master | 123 | 6 | 19,090 | `poc/results/corpus.json` |
| olake-fusion | master | 2,315 | 9 | 19,158 | `poc/results/corpus.json` |
| **Total** | | | **84** | **143,596** | `poc/results/corpus.json` |

Decision: an allowlist only (READMEs and other Markdown, Helm `values.yaml` and `Chart.yaml`, docker-compose files, example
configs, CLI flag definitions and driver config structs). Docs plus allowlisted repo files total 208 documents and
407,210 tokens (`poc/results/corpus.json`). PENDING(repos report: the exact globs, default branches, licenses, release cadence).
GitHub issues and discussions stay out of v1 (decision D5). PENDING(repos report: their volume and noise).

### 3.3 Outside sources

Allowed by the challenge "when the docs fall short" ([challenges page][ch]). Plan: a small curated allowlist (Apache
Iceberg maintenance and spec, catalog docs, PostgreSQL logical replication, MySQL binlog, MongoDB replica sets and oplog).
They are retrieved and cited only when no OLake source covers the point, and the answer labels them "outside source".
Precedence: OLake docs, then OLake repos, then outside sources. PENDING(olake-domain report: the exact URLs). Confirm
which domains count with K7.

### 3.4 Citation URL policy

- `sources` lists canonical page URLs exactly as the sitemap writes them (all 275 sitemap URLs end with `/`), with no
  `#anchor`, deduped, in the order the answer first cites them. Reason: it is the likeliest form to match a test set's
  expected pages. Anchors are for the UI.
- Repo files appear in `sources` as `https://github.com/datazip-inc/<repo>/blob/<default-branch>/<path>`. The UI links to the
  commit permalink with `#L<a>-L<b>`, adding `?plain=1` for Markdown so that GitHub honours line anchors (the POC
  chunker builds both forms, `poc/chunking/chunker.py`). Reason: the branch form always resolves and is the likeliest to match.
- In `answer`, the `[n]` markers are renumbered so that `[1]` is `sources[0]`.
- The POC scorer matches URLs leniently. It drops the scheme, fragment, query and trailing slash, and ignores the git ref in
  GitHub URLs (`poc/eval/questions.py`). The organizers' rule is unknown (K3).

### 3.5 Freshness

| Measurement | Value | Source |
|---|---|---|
| Docs `lastmod` spread | 100 of 124 docs pages on 2026-10-06, 16 on 2026-10-15, the rest spread between 2025-06-23 and 2026-10-12 | `poc/results/freshness.json` (`observations`) |
| HTTP validators | All 124 docs pages carry the same `Last-Modified` (the site deploy time), and the ETag encodes deploy mtime plus size. A conditional GET returns 304 in about 12 ms, but every page looks changed after every deploy | `poc/results/freshness.json` |
| GitHub REST API | Unauthenticated: 60 requests per hour, and each conditional request still costs 1. Authenticated: 5,000 per hour, and a 304 costs 0 | `poc/results/freshness.json` |
| `git ls-remote` | One repo's HEAD check takes 714-1005 ms and uses no API quota | `poc/results/freshness.json` |

Decision: incremental refresh keyed on the sitemap `lastmod` plus a content hash per page, and on `git ls-remote` HEAD SHAs
per repo. A new index version is built and swapped in atomically. The manifest (build time, docs `lastmod` max, repo SHAs)
appears in `/healthz` and the UI footer. PENDING(eval-ops report: in-app refresher vs a scheduled GitHub Action, and
host CPU behaviour for background work).

## 4. Architecture

### 4.1 Options

| | A. Simple | B. Hybrid + rerank + gates (chosen) | C. Agentic tool loop | D. Long-context stuffing |
|---|---|---|---|---|
| Retrieval | BM25 over heading-aware chunks, top 6 | BM25 + local dense, RRF k=60 [[rrf]], cross-encoder rerank, small-to-big | Tools (`search_docs`, `search_repo`, `open_page`) chosen by the LLM | None: the whole docs set goes in the prompt |
| LLM calls per answer | 1 | 1 (2 when gate 1 triggers a rewrite) | Several | 1, very large |
| Build effort | About 1 hour (memo estimate, unmeasured) | The 10:30-13:30 build window (plan section 3) | Not planned for v1 (memo) | Small, but rejected for serving |

### 4.2 Options against the judging criteria

Qualitative: the lead's design memo plus the doc-writer's reading of the options. These are judgments, not measurements.
PENDING(arch-prior-art report and POC retrieval numbers) will replace them with measurements where possible.

| Criterion (weight) | A. Simple | B. Chosen | C. Agentic | D. Long context |
|---|---|---|---|---|
| Answer accuracy (35) | Weak on paraphrased questions (lexical match only) | Dense recall plus rerank precision | Better on hard multi-hop questions | No retrieval misses, but the whole corpus is in every prompt |
| Citations and honesty (15) | `[n]` mapping; abstain only from the model | Three abstain triggers, citation validation | More steps between a citation and the retrieved text | Citations must name pages inside one huge context |
| Production readiness (20) | Few moving parts | More parts, but each one is local and deterministic | More failure modes (loops, tool errors) | Depends on a ~1M-token-context provider |
| UX and embedding (15) | Same widget | Same widget; streaming | Slower first token | Slowest |
| Engineering: latency and cost (15) | Cheapest | One LLM call; local retrieval has no marginal cost | 2-4x latency and cost (memo estimate, unmeasured) | Highest cost per answer |
| Engineering: freshness | Rebuild chunks | Rebuild chunks and vectors incrementally | Same as B | Re-send everything each call |

Decision: **B**, with **A** always available as the fallback: same chunks, same prompt, switched by `RETRIEVAL_MODE`.
C is a possible low-confidence escalation only if time allows. D is rejected for serving and kept as a debugging oracle.

### 4.3 Pipeline details

- **Chunking.** Split at headings and tab markers. Never split inside a code fence or table. Every chunk gets a
  `title › section` header. YAML and JSON split at keys, and Go at top-level declarations (`poc/chunking/chunker.py`). Measured
  sizes are in §9. PENDING(POC retrieval eval: target 300 or 600 tokens).
- **Retrieval.** BM25 (bm25s) and dense (fastembed) candidates fused with RRF, k=60 [[rrf]]. Then a cross-encoder
  rerank. Then small-to-big: the neighbouring chunk or parent section within about 4k context tokens, with at most 3 chunks
  per page. PENDING(POC: recall@k for BM25, dense, hybrid and hybrid+rerank).
- **Grounding.** One system prompt (plan section 4.3): answer only from numbered passages, cite `[n]` per claim, and copy
  configs exactly. Fixed `NO_ANSWER` and `OUT_OF_SCOPE` markers. Prompt injection is treated as data.
- **Abstain.** Three triggers, each logged: (1) the top rerank score is below the threshold after one rewrite; (2) the
  model emits the don't-know marker; (3) no valid citation is left after parsing. **Targets**: abstain recall ≥ 90% on
  unanswerable plus out-of-scope rows, and false-abstain ≤ 5% on answerable rows. PENDING(POC step 5: the tuned threshold
  and its curve).
- **Caching.** An exact-match LRU keyed on the normalized question plus the index version. No semantic cache, because a
  near-duplicate question can need a different answer. A stable system-prompt prefix lets providers cache the prompt.
- **Streaming.** `POST /ask/stream` sends SSE (`meta`, `token`, `done`, `error`) for the UI only. The browser reads it with
  `fetch()` because `EventSource` cannot POST [[mdn-es]].

## 5. Stack

PENDING(stack report) for every subsection. The memo's starting position is below.

### 5.1 LLM provider and models
Any OpenAI-compatible endpoint, configured by `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`, plus a fallback trio. The event's
credits provider is not named ([event page][ev]). The resource links on the challenges page point to Gemma 4 and the
Gemini API ([challenges page][ch]). The Gemini API has an OpenAI-compatible base URL,
`https://generativelanguage.googleapis.com/v1beta/openai/`, and supports streaming. Its OpenAI-library support is
described as beta [[gemini-openai]]. PENDING(stack report: models, prices, rate limits, Gemma 4 availability).

### 5.2 Cost per answer
About 4k input plus 400 output tokens per answer (memo estimate). Cache hits cost 0. PENDING(stack report prices; POC logged
token counts).

### 5.3 Embeddings and reranker
Local fastembed (ONNX on CPU), baked into the image. It does not depend on the provider, adds no marginal cost or rate limits,
is deterministic and works offline. API embeddings are the alternative if image size or host CPU becomes a problem.
PENDING(stack report / POC: model IDs, dimensions, sizes, CPU latency).

### 5.4 Vector store
None. Vectors stay in process as numpy brute force: 951-1,861 chunks without the blog, depending on chunk size
(`poc/results/chunks.json`). The index artifact is a directory (plan section 0.2, I1).

### 5.5 Host
PENDING(stack report: Cloud Run asia-south1 with min instances 1, DigitalOcean App Platform, Fly.io or Render, and a
Hugging Face Docker Space as the free fallback. Compare cold start, SSE support, CPU for background work, build path and cost).
A Cloudflare quick tunnel is for emergencies only: no uptime guarantee, no SSE, and a limit of 200 in-flight requests [[tunnel]].
Verified so far:
- **Hugging Face Docker Space**: creating one now needs a paid plan (PRO for personal accounts). The free CPU Basic
  hardware (2 vCPU, 16 GB RAM) sleeps when unused [[hf-overview]]. The container runs as uid 1000, listens on port 7860
  unless `app_port` says otherwise, and gets secrets as env vars at runtime [[hf-docker]]. It is no longer a *free* fallback.
- **Cloud Run**: `gcloud run deploy --source .` builds remotely, using the Dockerfile when there is one. `--min-instances` is
  set per revision, while `--min` is service-wide. `--no-cpu-throttling` keeps CPU allocated outside requests, which a
  background refresher needs. `--cpu-boost` is on by default for new services. `--set-secrets` maps env vars to Secret
  Manager versions [[gcloud-deploy]].

### 5.6 Widget pattern, CORS and CSP
A loader script injects a launcher and an iframe from our origin, so styles are isolated and the host page's CORS and
`connect-src` do not apply. `/embed` sends `Content-Security-Policy: frame-ancestors *` so any site can frame it [[csp-fa]].
Docusaurus can add the loader through its `scripts` config, which inserts tags into `<head>` [[docusaurus]].
The alternative is a Shadow DOM widget on the host page. PENDING(stack report: comparison).

### 5.7 Production basics
Pydantic validation (1-2000 characters), JSON errors, a 20 s LLM timeout with one jittered retry on 429/5xx, graceful
degradation, a concurrency semaphore that queues, a generous per-IP rate limit, CORS `*` without credentials, structured
JSON logs, `Server-Timing`, a non-root container user, and secrets only in env.

### 5.8 Latency and cost targets
**Targets** (unmeasured): `/ask` p50 ≤ 3 s and p95 ≤ 6 s with a Flash-class model; stream time to first token ≤ 1.2 s;
retrieval plus rerank ≤ 150 ms on 2 vCPU. PENDING(POC latency measurements).

## 6. Evaluation

Method: [eval-questions.md](eval-questions.md). The POC scorer (`poc/eval/score.py`) checks the response schema
(exactly `answer` and `sources`), the source hit with normalized URLs, behaviour by question type (abstain or decline
where expected), latency p50 and p95, and must-mention fact coverage judged by an LLM.

PENDING(POC results: retrieval recall@k per method, end-to-end accuracy, abstain confusion matrix, threshold curve,
latency and cost per answer).

## 7. Prior art and what judges probe

PENDING(arch-prior-art report).

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Credits throttle or stop during post-freeze scoring | Every row fails | A personal fallback trio (env only); a degraded mode that returns the most relevant pages; ask at kickoff (K1) |
| Endpoint down, cold or rate-limited while scoring | Production readiness and accuracy both lose | Min instances ≥ 1, a queue rather than rejection, a very high rate limit, a synthetic probe every minute (plan section 9) |
| The organizers match sources differently from us | Citation points lost | Canonical sitemap URLs and branch-form GitHub URLs; ask K3; matching in our own eval is lenient |
| Over-abstaining or under-abstaining | Accuracy or honesty points lost | Three logged triggers and a threshold tuned on the eval set (§4.3) |
| Venue Wi-Fi | Slow builds and deploys | Pre-cached wheels, models, repos and base image; remote builds; phone hotspot (plan section 11) |
| A teammate edits another track's files | Lost work | One owner per path (plan section 0.3) |
| Unclear pre-existing-code policy | Disqualification | Bring only documents to the event, write code there, disclose (K6, D2) |

## 9. Appendix: measurement table

| Metric | Value | Method or source |
|---|---|---|
| Sitemap URLs (total, `/docs/`, `/blog/`, other) | 275, 124, 86, 65 | Sitemap fetch and count, 2026-10-16T17:14Z; `poc/results/corpus.json` |
| Sitemap URLs with `lastmod` | 231 | Same sitemap count |
| Docs tokens (o200k_base) | 263,614 | `poc/results/corpus.json` |
| Docs tokens per page (p50, max) | 1,152; 30,229 | `poc/results/corpus.json` |
| Blog tokens (85 posts) | 446,137 | `poc/results/corpus.json` |
| Allowlisted repo files and tokens | 84 files, 143,596 tokens | `poc/results/corpus.json` |
| Docs plus repos | 208 documents, 407,210 tokens | `poc/results/corpus.json` |
| Fetch of 209 pages at concurrency 4 | 12.77 s (per page p50 0.243 s) | `poc/results/corpus.json` |
| Chunks at target 300 / hard max 450 (no blog) | 1,861 (docs 1,248, repo 613); tokens p50 235, p95 420, max 501; 4 over hard max | `poc/results/chunks.json` |
| Chunks at target 600 / hard max 900 (no blog) | 951 (docs 622, repo 329); tokens p50 470, p95 815, max 881; 0 over hard max | `poc/results/chunks.json` |
| Conditional GET to olake.io (304) | ≈ 12 ms | `poc/results/freshness.json` |
| `git ls-remote` per repo | 714-1005 ms | `poc/results/freshness.json` |
| GitHub API limit (unauthenticated, authenticated) | 60 per hour, 5,000 per hour | `poc/results/freshness.json` |
| Retrieval recall@k, accuracy, abstain, latency, cost | PENDING | POC steps 3-6 |

## Sources

[ev]: https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake
[ch]: https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges
[sitemap]: https://olake.io/sitemap.xml
[rrf]: https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
[mdn-es]: https://developer.mozilla.org/en-US/docs/Web/API/EventSource/EventSource
[gemini-openai]: https://ai.google.dev/gemini-api/docs/openai
[tunnel]: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
[csp-fa]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors
[docusaurus]: https://docusaurus.io/docs/api/docusaurus-config
[hf-overview]: https://huggingface.co/docs/hub/spaces-overview
[hf-docker]: https://huggingface.co/docs/hub/spaces-sdks-docker
[gcloud-deploy]: https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy

- Event page: <https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake>
- Challenges page: <https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges>
- OLake sitemap: <https://olake.io/sitemap.xml>
- Cormack, Clarke and Buettcher (2009), Reciprocal Rank Fusion (k = 60): <https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf>
- MDN `EventSource()`: <https://developer.mozilla.org/en-US/docs/Web/API/EventSource/EventSource>
- Gemini API OpenAI compatibility: <https://ai.google.dev/gemini-api/docs/openai>
- Cloudflare quick tunnels: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/>
- MDN CSP `frame-ancestors`: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors>
- Docusaurus `scripts` config: <https://docusaurus.io/docs/api/docusaurus-config>
- Hugging Face Spaces overview: <https://huggingface.co/docs/hub/spaces-overview>
- Hugging Face Docker Spaces: <https://huggingface.co/docs/hub/spaces-sdks-docker>
- `gcloud run deploy` reference: <https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy>
- POC measurements: `poc/results/corpus.json`, `poc/results/chunks.json`, `poc/results/freshness.json`; POC code `poc/chunking/chunker.py`, `poc/eval/questions.py`, `poc/eval/score.py`
