Research agent output, 2026-10-16; evidence for docs/research.md

# stack

## Summary
The harness blocked writing report.md ("Subagents should return findings as text"), so the full report is in these fields. Small notes, scripts and POC code are kept under scratchpad/wf/stack/{notes,scripts,poc}. Nothing was written to the worktree.

1. CREDITS ARE UNCONFIRMED. The MLH Gemma links point to Gemma 4 on the Gemini API. Only gemma-4-31b-it and gemma-4-26b-a4b-it are served, on the free tier only: paid tier is 'Not available' and free-tier data is 'used to improve our products'. The MLH DigitalOcean page promises $200, but its signup link returns a 302 to the DO homepage (measured), and DO docs describe only an automatic $5 signup credit.

2. GEMMA 4. Sizes are E2B, E4B, 12B, 26B A4B (MoE, 3.8B active) and 31B; Apache-2.0; 128K or 256K context. Ollama has gemma4:e2b through :31b at 4.6–20 GB. At roughly 35–47 tok/s on AI Studio or DO, a 400-token answer takes about 9–12 s.
   - The OpenAI-compatible Gemini endpoint is not documented for Gemma. Artificial Analysis marks AI Studio Gemma as OpenAI-compatible, so test it on the day.

3. GEMINI MODELS. Current Flash-class IDs: gemini-3.8-flash ($0.75/$3.75 per 1M tokens, doubling from 2027-01-01), gemini-3.6-flash, gemini-3.5-flash-lite ($0.30/$2.50) and gemini-3.1-flash-lite ($0.25/$1.50).
   - The 2.5 models are restricted to past users.
   - Gemini 3 reasoning cannot be turned off; minimal or low is the floor.
   - The OpenAI-compatible endpoint is labelled beta.
   - Embeddings: gemini-embedding-2, $0.20 per 1M tokens, 8,192-token input, 128–3072 dims.

4. DIGITALOCEAN. Inference is OpenAI-compatible at https://inference.do-ai.run/v1. Prices: gemma-4-31B-it $0.18/$0.50, openai-gpt-oss-120b $0.10/$0.70. Tier 1 gets 120 RPM and 1.5M TPM. Tiers 1–2 cannot use Anthropic or OpenAI proprietary models. Inference is prepaid only.
   - App Platform has a BLR (Bangalore) region at $5/$10/$12 per month. It sits behind Cloudflare, and SSE buffering and a 100-second cap are reported only by community threads (unverified).

5. COST IS NOT THE DECIDER. At 4k input + 400 output tokens, an answer costs $0.0004–$0.0045: GPT-6 Luna and Claude Haiku 5.5 $0.0006, Groq gpt-oss-120b $0.00084, DO Gemma 4 31B $0.00092, Gemini 3.5 Flash-Lite $0.0022, Gemini 3.8 Flash $0.0045. Reasoning settings drive time-to-first-token from 0.4 s to 24 s (Artificial Analysis).

6. FREE TIERS WILL THROTTLE THE HIDDEN-TEST BURST. Groq free allows 8K TPM, which is about 2 requests a minute at 4k tokens. Cerebras free trial allows 5 RPM. Gemini free limits are visible only in AI Studio, and a third-party snapshot reports Gemma 4 at 15 RPM / 1,500 RPD. Use a paid key, a fallback chain, a global semaphore and generous per-IP limits.

7. RETRIEVAL. The olake.io corpus is about 2.3k–3.8k chunks (sampled). Measured query times: numpy exact 0.35 ms at 20k×384, bm25s 0.10 ms, FAISS flat 0.24 ms, sqlite-vec 1.4 ms, SQLite FTS5 3.5 ms, rank_bm25 13.8 ms. Keep retrieval in-process; no vector DB is needed.

8. LOCAL MODELS.
   - Embedding: bge-small-en-v1.5 scores 51.68 on MTEB retrieval, about the same as text-embedding-3-small (51.08). A query embeds in 2.3 ms, but the corpus embeds at about 10 chunks/s on 2 threads, so precompute offline.
   - Image size and memory: the compressed image grows from 73 MB to 180 MB and idle memory from 59 MiB to 189 MiB.
   - Rerankers: FlashRank TinyBERT reranks 20 candidates in 14 ms; MiniLM-L-6 takes 215–303 ms.

9. HOSTING.
   - Default: Cloud Run asia-south1 (Mumbai). Measured round-trip from this IST machine is 41 ms, versus 260–390 ms to US/EU. Streaming and health probes are documented. min-instances=1 costs about $0.32/day.
   - Fallback: DO App Platform in BLR.
   - Gotchas: Hugging Face Docker Spaces now require PRO ($9/month). Fly has no India region and a trial of only 2 hours of machine runtime. Render free spins down and shows a loading page. Cloudflare quick tunnels have no SSE support.

10. WIDGET. kapa and Inkeep both ship one script that mounts Shadow DOM and streams with fetch (measured from their bundles). olake.io is Docusaurus 3.10.2 on GitHub Pages with no CSP and no X-Frame-Options (measured), and its docs accept theme messages when embedded in an iframe. Load the widget through the Docusaurus 'scripts' option with async: true, and have it follow html[data-theme].

11. OPS.
   - FastAPI 0.135+ has native SSE and sets no-cache and X-Accel-Buffering: no (verified in the POC).
   - The OpenAI SDK defaults to a 10-minute timeout with 2 retries; set it to about 25 s.
   - Provider prompt caching saves little for RAG, because Gemini 3.8 Flash needs a 4,096-token identical prefix. An application-level answer cache saves much more.

12. DEVIATIONS. About 1 GB was downloaded in total (budget 600 MB); all of it has been deleted. gh api calls against the datazip-inc repos were denied by the permission system.

## Recommendations
- **LLM client: use the openai Python SDK with base_url, model and key from env vars, and an ordered fallback list of (base_url, model) pairs. Set timeout to about 25 s and max_retries to 1, and fail over to the next provider before the first streamed byte. Do not depend on response_format; parse defensively.** — Every candidate provider exposes an OpenAI-compatible chat endpoint. The SDK is 2.2 MB, against 38.8 MB for LiteLLM. Its default timeout is 10 minutes and it does not retry streams. Anthropic ignores response_format, DO does not document it, and it is unverified for Gemma on the Gemini API. [evidence: https://raw.githubusercontent.com/openai/openai-python/main/README.md; https://platform.claude.com/docs/en/api/openai-sdk; https://docs.digitalocean.com/reference/api/reference/serverless-inference/; measured: PyPI wheel sizes]
- **Generator default: gemini-3.8-flash with reasoning_effort 'low', or gemini-3.5-flash-lite with 'minimal' if latency matters most, on a paid Tier 1 key through the OpenAI-compatible endpoint. Compare against gpt-6-luna (non-reasoning) and claude-haiku-5-5 on the eval set before freezing.** — gemini-3.8-flash scores highest among current Flash-class models on Artificial Analysis (40.9) with 1M context and structured outputs, at about $0.0045 per answer. Reasoning cannot be turned off on Gemini 3, so low or minimal is needed to keep latency acceptable. A paid tier avoids free-tier data use and the per-project RPD caps. [evidence: https://ai.google.dev/gemini-api/docs/pricing; https://ai.google.dev/gemini-api/docs/openai; measured: artificialanalysis.ai leaderboard payload]
- **Generator fallbacks, in order: (1) DO serverless openai-gpt-oss-120b or gemma-4-31B-it on DO credits; (2) Groq openai/gpt-oss-120b on a developer key; (3) gemma-4-26b-a4b-it on the Gemini free tier as a last resort.** — DO is OpenAI-compatible, gives Tier 1 120 RPM / 1.5M TPM and costs about $0.0007–0.0009 per answer. Groq has the fastest TTFT (0.71 s at 474 tok/s), but its free plan is only 8K TPM. Gemini-free Gemma costs nothing but is about 15 RPM (3P), sends data to Google, and its OpenAI-compat path is unverified. [evidence: https://docs.digitalocean.com/products/inference/details/limits/; https://docs.digitalocean.com/products/inference/details/pricing/; https://console.groq.com/docs/rate-limits; https://tilnote.io/pages/6a51b3398d9a59d14c1c174c (3P)]
- **Embeddings: local fastembed BAAI/bge-small-en-v1.5 (384 dims). Precompute corpus vectors at build or CI time into a .npy baked into the image, and embed only the query at runtime. Fallbacks: snowflake-arctic-embed-m, or API gemini-embedding-2 / voyage-4-lite if the eval shows better recall.** — Query embedding takes 2.3 ms with no network dependency. MTEB retrieval is 51.68, about the same as text-embedding-3-small (51.08). The model is MIT-licensed and adds only 107 MB compressed to the image. Corpus embedding at about 10 chunks/s on 2 vCPU is too slow for container startup. [evidence: https://huggingface.co/BAAI/bge-small-en-v1.5; https://huggingface.co/Snowflake/snowflake-arctic-embed-s; measured: bench_embed2 and docker image sizes]
- **Retrieval: hybrid search in-process. Use bm25s for BM25 (SQLite FTS5 as fallback) and numpy exact cosine for vectors (FAISS flat as fallback), fused with RRF. Do not use a vector DB service.** — At the 2.3k–20k chunk scale, queries take 0.1–0.35 ms (measured). There is nothing to operate and no network hop. The Qdrant and Supabase free tiers pause after a week unused. [evidence: measured: bench_lexical / bench_vector; https://qdrant.tech/documentation/cloud/create-cluster/; https://supabase.com/pricing]
- **Reranking: off by default. Enable FlashRank ms-marco-TinyBERT-L-2-v2 only if the eval shows a gain; Voyage rerank-3-lite is the API alternative.** — TinyBERT adds 14 ms for 20 candidates. MiniLM cross-encoders add 215–300 ms or more, which is not worth it unless accuracy improves. Voyage rerank-3-lite costs $0.02/1M tokens with 200M free. [evidence: measured: bench_rerank_lowload; https://raw.githubusercontent.com/PrithivirajDamodaran/FlashRank/main/README.md; https://docs.voyageai.com/docs/pricing]
- **API: FastAPI 0.135 or later.
- POST /ask: JSON contract only.
- POST /ask/stream: native SSE, for the widget only.
- /healthz (liveness) and /readyz (index loaded).
- CORS: allow_origins *, no credentials, max_age 86400, expose x-request-id.
- Exception handlers that always return {answer, sources}.
- Token bucket per client at 60–120/min, plus a global asyncio semaphore and a daily token budget.
- In-process answer cache keyed by normalized question.
- JSON logs carrying request_id.** — Verified in the local POC. The hidden test set will likely be sent as a burst from one IP, so per-IP limits must not throttle the grader. An answer cache saves more than provider prompt caching for RAG. [evidence: https://fastapi.tiangolo.com/tutorial/server-sent-events/; https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS; measured: poc/app.py tests; https://ai.google.dev/gemini-api/docs/caching]
- **Hosting default: Google Cloud Run in asia-south1 with min-instances=1, 1 vCPU and 512 MiB–1 GiB, a request timeout of about 60 s, and startup plus liveness probes.** — Mumbai is 41 ms from the venue-area machine, against 260–390 ms to US/EU (measured). Streaming, probes and min-instances are documented. Idle cost is about $0.32/day and the free tier offsets around $5/month. [evidence: https://cloud.google.com/run/pricing; https://cloud.google.com/run/docs/triggering/https-request; https://cloud.google.com/run/docs/configuring/healthchecks; measured: gcping latency]
- **Hosting fallback: DigitalOcean App Platform in the BLR region ($5 for 512 MiB fixed, or $12 for 1 GiB scalable), with health_check and liveness_health_check, keeping /ask non-streaming. Emergency only: ngrok free dev domain from a laptop. Avoid Cloudflare quick tunnels, Fly (no India region, 2-hour trial), Render free (spin-down with a loading page) and Hugging Face Docker Spaces unless PRO is already paid.** — BLR is in Bangalore and can use DO credits, but SSE buffering and a 100 s cap there are unverified. ngrok keeps a stable URL and its interstitial skips API traffic; quick tunnels have no SSE and random URLs. [evidence: https://docs.digitalocean.com/products/app-platform/details/availability/; https://docs.digitalocean.com/products/app-platform/details/pricing/; https://ngrok.com/docs/pricing-limits/free-plan-limits/; https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/; https://fly.io/docs/about/pricing/; https://render.com/docs/free; https://huggingface.co/docs/hub/spaces-overview]
- **Widget: one async script served from the API origin, loaded as <script async src=API/widget.js data-api=API>. It mounts a Shadow DOM floating panel and streams via fetch + getReader with a /ask fallback. It follows html[data-theme], uses role=dialog, role=log and aria-busy, closes on Escape and restores focus, renders with textContent only, and links https sources only. Docusaurus: scripts: [{src, async: true, 'data-api': ...}]. Fallback embed: an iframe /embed page.** — This mirrors kapa.ai and Inkeep (measured from their bundles). olake.io has no CSP or X-Frame-Options and supports dark/light theming, including when embedded in an iframe. Docusaurus scripts are render-blocking without async. The POC is written and tested with Node. [evidence: measured: kapa and Inkeep bundle analysis; measured: olake.io headers and message-listener.js; https://docusaurus.io/docs/api/docusaurus-config; https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/log_role; poc/widget/widget.js, ask-client.js]
- **Before freezing the stack, run the day-of checks:
(1) curl gemma-4-26b-a4b-it on /v1beta/openai/chat/completions with stream:true and response_format.
(2) Read the project's AI Studio rate-limit page.
(3) GET inference.do-ai.run/v1/models with a DO key and read the x-ratelimit headers.
(4) From the deployed URL, test the olake.io preflight and SSE chunk timing.
(5) Fire 50 concurrent /ask requests to simulate the grader.** — These are the unverified assumptions on the critical path: Gemma via OpenAI-compat, free-tier quotas, DO tier access, and platform buffering. [evidence: https://ai.google.dev/gemini-api/docs/openai; https://ai.google.dev/gemini-api/docs/rate-limits; https://docs.digitalocean.com/products/inference/reference/quota-specific-response-headers/]

## Measurements
- MLH DO signup link behaviour: **try.digitalocean.com/freetrialoffer/ returns 302 to https://www.digitalocean.com** (curl -D (twice, with and without query string))
- HTTPS RTT to Cloud Run regions from venue-area machine (IST): **Mumbai 41.5 ms; Delhi 53.4 ms; Singapore 53.0 ms; Iowa 261.7 ms; Belgium 360.2 ms; S. Carolina 387.9 ms (warm medians, n=7)** (scripts/ping_regions.py over https://gcping.com/api/endpoints)
- TCP connect to LLM API edges: **6-21 ms for Gemini, OpenAI, Anthropic, Groq, Cerebras, OpenRouter, Together and DO; about 258 ms for DeepInfra** (curl -w %{time_connect} x3 per host)
- olake.io corpus size estimate: **docs ~162k words (811-1,352 chunks); blog ~292k words (1,458-2,429 chunks); site total ~2.3k-3.8k chunks** (scripts/olake_sample.py, 12 docs + 12 blog pages sampled from sitemap.xml)
- bm25s query p50 (20k chunks): **0.10 ms (index 923 ms); 0.02 ms at 2k** (scripts/bench_lexical.py, uv run --with bm25s)
- SQLite FTS5 bm25() query p50 (20k): **3.5 ms (index 264 ms)** (scripts/bench_lexical.py, stdlib sqlite 3.50.4)
- rank_bm25 query p50 (20k): **13.8 ms** (scripts/bench_lexical.py)
- tantivy-py query p50 (20k): **0.13 ms (index 400 ms)** (scripts/bench_lexical.py)
- numpy exact vector search p50 (20k x 384 / 768): **0.35 ms / 0.68 ms** (scripts/bench_vector.py, random unit vectors, top-20)
- FAISS IndexFlatIP p50 (20k x 384): **0.24 ms** (scripts/bench_vector.py, faiss-cpu 1.15.1)
- sqlite-vec / Chroma / LanceDB p50 (20k x 384): **1.40 ms / 1.31 ms (build 3.0 s) / 3.71 ms** (scripts/bench_vector.py)
- bge-small-en-v1.5 local embedding throughput (2 threads, low load): **10.6 chunks/s (~180-word chunks); query embed p50 2.3 ms** (scripts/bench_embed2.py, fastembed 0.9.0 on an Apple M5 Max)
- Reranker latency, 20 / 50 candidates (low load): **FlashRank TinyBERT 13.9 / 41.7 ms; fastembed MiniLM-L-6 215 / 863 ms; FlashRank MiniLM-L-12 285 / 1,176 ms** (scripts/bench_rerank.py)
- Container image size (compressed) and idle RSS: **lean 73 MB / 59 MiB; with fastembed + bge-small 180 MB / 189 MiB** (docker build + docker save | gzip | wc -c; docker stats (--cpus=1 --memory=1g))
- Container cold start to readiness: **1.28 s lean; 1.24 s local-embed (app startup 0.53 / 0.71 s)** (docker run, then poll /readyz)
- Cost per answer (4k in / 400 out): **GPT-6 Luna $0.00060; Haiku 5.5 $0.00060; Groq gpt-oss-120b $0.00084; DO Gemma 4 31B $0.00092; Gemini 3.5 Flash-Lite $0.00220; Gemini 3.8 Flash $0.00450; Gemma on Gemini free tier $0** (scripts/cost.py using list prices from provider pricing pages)
- Cloud Run min-instance idle cost (1 vCPU, 0.5 GiB, Tier 1): **about $0.324/day; about $9.72 per 30 days before free-tier offset** (computed from https://cloud.google.com/run/pricing idle rates of $0.0000025 per vCPU-s and per GiB-s)
- Gemma 4 / Gemini speeds (Artificial Analysis): **AI Studio Gemma 4 31B 35.3 tok/s, TTFT 1.04 s; 26B A4B 46.8 tok/s, 0.97 s; DO Gemma 4 31B 44-47.6 tok/s, ~2 s; Gemini 3.5 Flash-Lite 446 tok/s, 6.98 s; Groq gpt-oss-120b 474 tok/s, 0.71 s; Cerebras 1,729 tok/s, 0.42 s** (parsed RSC payloads of artificialanalysis.ai leaderboard and provider pages (scripts/aa_parse.py, scripts/aa_providers.py))
- kapa.ai widget bundle: **2,130,950 bytes raw, 605,382 bytes compressed; attachShadow x1 (mode open); no iframe creation; body.getReader x1; aria-live x1; aria-modal x1** (curl download + grep -F counts (not executed))
- Inkeep embed bundle: **1,655,186 bytes; attachShadow x1; getReader x1; aria-live x4; no iframe creation** (curl download + grep -F counts (not executed))
- olake.io response headers: **server GitHub.com; Fastly POP cache-maa (Chennai); no CSP; no X-Frame-Options; Docusaurus v3.10.2; Algolia DocSearch** (curl -D https://olake.io/docs/ + HTML grep)
- POC API contract checks: **preflight 200 with allow-origin *, max-age 86400; POST returns {answer, sources} with x-request-id; SSE headers text/event-stream + no-cache + x-accel-buffering no; token bucket returns 429 + retry-after** (poc/app.py run locally, tested with curl)
- SSE-over-POST browser client: **25 events parsed; first delta at 37 ms; JSON fallback OK** (node poc/widget/test-client.mjs against the local POC server)
- Python wheel sizes (linux x86_64): **openai 2.2 MB; litellm 38.8 MB; numpy 16.7 MB; faiss-cpu 18.8 MB; onnxruntime 23.8 MB; lancedb 75.2 MB; pyarrow 53.9 MB; torch 554.6 MB; hnswlib sdist only** (scripts/pypi_sizes.py (PyPI JSON API))

## Findings
- [high] *credits/mlh-links*: MLH short links resolve as follows (via meta refresh): gemma lands on www.mlh.com/partners/gemma; gemma-quickstart on ai.google.dev/gemma/docs/core/gemma_on_gemini_api; gemma-docs on ai.google.dev/gemma/docs/get_started; gemma-beginnerguide on github.com/google-gemma/cookbook; digitalocean on mlh.com/partners/digitalocean; digitalocean-gradient on docs.digitalocean.com/products/gradient-ai-platform/ (now titled Inference); digitalocean-signup on try.digitalocean.com/freetrialoffer/, which returns HTTP 302 to www.digitalocean.com. [evidence: measured: curl of each mlh.link URL plus grep of http-equiv refresh; curl -D on try.digitalocean.com/freetrialoffer/ returned 302 with location https://www.digitalocean.com (twice); https://www.mlh.com/partners/gemma; https://mlh.com/partners/digitalocean]
- [high] *credits/digitalocean*: The MLH DigitalOcean page promises $200 for signing up through the MLH link, but that signup link currently redirects to the DO homepage. DO's own docs describe only an automatic $5 signup credit that expires after 90 days and requires a payment method. The $200 path is unverified. [evidence: https://mlh.com/partners/digitalocean; https://docs.digitalocean.com/platform/billing/signup-credit/; measured: curl -D https://try.digitalocean.com/freetrialoffer/ returned 302 to https://www.digitalocean.com]
- [high] *gemma4/models*: Gemma 4 comes in five sizes: E2B (2.3B effective), E4B (4.5B effective), 12B Unified (11.95B), 26B A4B MoE (25.2B total, 3.8B active, 8 of 128 experts plus 1 shared) and 31B Dense (30.7B). License is Apache 2.0. Context is 128K for E2B/E4B and 256K for the rest. Audio input is supported only on E2B, E4B and 12B. The ai.google.dev Gemma docs are marked deprecated in favour of gemma.ai. [evidence: https://gemma.ai/models/gemma-4/model-card/; https://ai.google.dev/gemma/docs/get_started; https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api]
- [high] *gemma4/gemini-api*: The Gemini API hosts only gemma-4-31b-it and gemma-4-26b-a4b-it; smaller sizes are not hosted. Documented features: system_instruction, function calling, thinking_level (high or minimal), image input and Search grounding. JSON/structured output, streaming and the API context limit are not documented for Gemma. [evidence: https://gemma.ai/deployment/gemini-api/; https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api]
- [medium] *gemma4/pricing-limits*: Gemma 4 on the Gemini API is free-tier only: input, output and caching are free, the paid tier is 'Not available', and free-tier data is 'Used to improve our products: Yes'. RPM/RPD are not published; the docs say to check AI Studio, and limits apply per project rather than per key. A third-party snapshot dated 2026-07-11 reports 15 RPM, unlimited TPM and 1,500 RPD for both Gemma 4 models, and 20 RPD for 'Gemini 3.5 Flash'. [evidence: https://ai.google.dev/gemini-api/docs/pricing; https://ai.google.dev/gemini-api/docs/rate-limits; https://tilnote.io/pages/6a51b3398d9a59d14c1c174c (3P); https://discuss.ai.google.dev/t/questions-about-gemma-models/100257 (3P, Gemma 3 era: 30 RPM / 15K TPM / 14.4K RPD)]
- [low] *gemma4/openai-compat*: No Google page says Gemma works on the OpenAI-compatible endpoint; the OpenAI-compat page never mentions Gemma. Artificial Analysis lists 'Google (AI Studio)' as a provider for Gemma 4 31B and 26B A4B with openaiCompatible=true, so it is plausible. Verify with a key on the day. [evidence: https://ai.google.dev/gemini-api/docs/openai; measured: parsed provider payloads of https://artificialanalysis.ai/models/gemma-4-31b/providers and https://artificialanalysis.ai/models/gemma-4-26b-a4b/providers]
- [medium] *gemma4/speed*: Artificial Analysis medians: AI Studio Gemma 4 31B runs at 35.3 tok/s with 1.04 s TTFT, and 26B A4B at 46.8 tok/s with 0.97 s. DigitalOcean Gemma 4 31B runs at 44.0 tok/s with 2.12 s TTFT (47.6 tok/s and 1.98 s non-reasoning). Modular NVFP4 reaches 313.7 tok/s. A 400-token answer from Google or DO therefore takes about 9–12 s. [evidence: measured: parsed https://artificialanalysis.ai/models/gemma-4-31b/providers, /models/gemma-4-26b-a4b/providers, /models/gemma-4-31b-non-reasoning/providers]
- [high] *gemma4/paid-hosts*: Gemma 4 is cheap at paid hosts:
- OpenRouter lists 15 endpoints for gemma-4-31b-it ($0.10–$0.75 input) and 13 for gemma-4-26b-a4b-it ($0.042–$0.15 input), including Google Vertex at $0.15/$0.60.
- DeepInfra: gemma-4-26B-A4B-it $0.07/$0.34, gemma-4-31B-it $0.20/$0.40.
- Together: Gemma 4 31B $0.39/$0.97.
- Cloudflare Workers AI: @cf/google/gemma-4-26b-a4b-it $0.10/$0.30. [evidence: measured: https://openrouter.ai/api/v1/models/google/gemma-4-31b-it/endpoints and /google/gemma-4-26b-a4b-it/endpoints; https://deepinfra.com/pricing; https://www.together.ai/pricing; https://developers.cloudflare.com/workers-ai/platform/pricing/]
- [high] *gemma4/ollama*: Ollama hosts all Gemma 4 sizes:
- gemma4:e2b: 4.6–7.5 GB, 128K context.
- gemma4:e4b (= latest): 6.6–9.5 GB, 128K.
- gemma4:12b: 7.7–8.0 GB (12b-it-qat 7.2 GB), 256K.
- gemma4:26b: 16–19 GB (26b-a4b-it-q4_K_M 18 GB), 256K.
- gemma4:31b: 19–20 GB, 256K.
Also listed: mlx, nvfp4, mxfp8, bf16 and qat variants, plus cloud tags. Ollama publishes Gemma 4 as text and image only and sizes context from VRAM. Ollama 0.33.3 is installed locally with no gemma4 pulled. [evidence: https://ollama.com/library/gemma4/tags; https://gemma.ai/deployment/ollama/; measured: ollama list / ollama --version]
- [high] *gemini/flash-models*: Stable Flash-class IDs are gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash-lite and gemini-3.1-flash-lite, plus preview gemini-3-flash-preview. The 2.5 models are restricted to users who used them before; Google tells new projects to use 3.5 Flash-Lite or 3.8 Flash. All four stable models have 1,048,576 input and 65,536 output tokens and support structured outputs, function calling, caching, thinking and the Batch API. gemini-3.7-flash appears on OpenRouter and Artificial Analysis but not on the Gemini API models page. [evidence: https://ai.google.dev/gemini-api/docs/models; https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite; https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash; https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite; https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash]
- [high] *gemini/pricing*: Paid prices per 1M tokens (input / output including thinking / cache read):
- 3.8-flash: $0.75 / $3.75 / $0.075 through 2026-12-31, then $1.50 / $7.50 from 2027-01-01.
- 3.6-flash: same as 3.8-flash for 2026.
- 3.5-flash-lite: $0.30 / $2.50 / $0.03.
- 3.1-flash-lite: $0.25 / $1.50 / $0.025.
- 3-flash-preview: $0.50 / $3.00.
- 2.5-flash-lite (restricted): $0.10 / $0.40.
Batch is 50% off. All of these models have a $0 free tier, where data is used for product improvement. [evidence: https://ai.google.dev/gemini-api/docs/pricing (last updated 2026-10-15, verified against raw text)]
- [high] *gemini/tiers*: Free tier requires an active project or free trial. Tier 1 requires a linked billing account; the upgrade is usually immediate and Tier 1 has a $10 spend cap per rolling 10 minutes. Tier 2 requires $100 paid plus 3 days. RPD resets at midnight Pacific. Per-model RPM/TPM/RPD are shown only in AI Studio. [evidence: https://ai.google.dev/gemini-api/docs/rate-limits]
- [high] *gemini/openai-compat*: The OpenAI-compatible base URL is https://generativelanguage.googleapis.com/v1beta/openai/. It supports chat, stream, tools, structured output (parse with Pydantic/Zod), image and audio input, reasoning_effort (minimal/low/medium/high mapped to thinking_level), extra_body (cached_content, thinking_config), embeddings, models, Batch (partial) and service_tier (flex or priority). Reasoning cannot be turned off for Gemini 2.5 Pro or Gemini 3 models, and library support is described as still in beta. The page names embedding models gemini-embedding-2-preview and gemini-embedding-001, while the embeddings page names gemini-embedding-2. [evidence: https://ai.google.dev/gemini-api/docs/openai]
- [high] *gemini/embeddings*: gemini-embedding-2 accepts text, image, video, audio and PDF, up to 8,192 input tokens. Output is 128–3072 dims (768/1536/3072 recommended) and truncated dims are auto-normalized. There is no task_type; task instructions go in the prompt. Price: text $0.20/1M paid ($0.10 batch), free on the free tier.
gemini-embedding-001 is text-only with 2,048 input tokens and uses task_type (RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT). OpenRouter lists it at $0.15/1M.
The two embedding spaces are incompatible. Rate limits are not published; the Tier 1 batch enqueued-token cap for Gemini Embedding is 500,000. [evidence: https://ai.google.dev/gemini-api/docs/embeddings; https://ai.google.dev/gemini-api/docs/pricing; https://ai.google.dev/gemini-api/docs/rate-limits; measured: https://openrouter.ai/api/v1/embeddings/models]
- [high] *digitalocean/inference*: DO Inference (formerly Gradient AI) serverless runs at base https://inference.do-ai.run with OpenAI-compatible /v1/chat/completions, /v1/responses, /v1/embeddings and /v1/models, plus /v1/messages; 'all text models' are OpenAI-compatible. Chat supports stream (SSE) with stream_options and function tools. response_format is not documented for chat. Embeddings take 1–2,048 strings, reject unknown fields, and do not stream. Billing is prepaid only: promotional credits or a prepaid balance. [evidence: https://docs.digitalocean.com/products/inference/how-to/si-endpoints/; https://docs.digitalocean.com/products/inference/details/models/; https://docs.digitalocean.com/reference/api/reference/serverless-inference/; https://docs.digitalocean.com/products/inference/details/pricing/]
- [high] *digitalocean/models-prices*: Open models on DO serverless (USD per 1M tokens):
- gemma-4-31B-it: 256,000 context, 8,192 max output, $0.18/$0.50, cache read $0.036.
- openai-gpt-oss-120b: 128K context, 4,096 max output, $0.10/$0.70.
- openai-gpt-oss-20b: $0.05/$0.45.
- llama-4-maverick: $0.25/$0.87.
- mistral-3-14B (Ministral 3 14B): $0.20/$0.20.
- qwen3.5-397b-a17b: $0.55/$3.50.
- deepseek-4-flash: $0.14/$0.28; deepseek-v4.1-flash: $0.30/$1.20.
- GLM-5.3-Flash: $0.15/$0.50.
Llama 3.1 8B, Qwen 2.5 14B and Mistral 7B are dedicated-only.
Embedding models, priced under knowledge bases: all-mini-lm-l6-v2 $0.009, gte-large-en-v1.5 $0.09, Qwen3 Embedding 0.6B $0.04, BGE-M3 $0.02; BGE reranker v2 m3 $0.01 (knowledge bases only). [evidence: https://docs.digitalocean.com/products/inference/details/models/; https://docs.digitalocean.com/products/inference/details/pricing/]
- [high] *digitalocean/limits*: Serverless rate limits: Tier 1 up to 120 RPM and 1.5M TPM; Tier 5 up to 1,200 RPM and 25M TPM. Limits vary by model and are returned in x-ratelimit-{limit,remaining,reset}-* headers. Tiers 1 and 2 cannot use Anthropic models or OpenAI proprietary models (gpt-oss excepted). Limits are 'maximums on shared capacity, not guarantees'. The availability table lists only Dedicated, BYOM and Agents (TOR1, ATL1, RIC1, NYC2); serverless is a global endpoint. [evidence: https://docs.digitalocean.com/products/inference/details/limits/; https://docs.digitalocean.com/products/inference/reference/quota-specific-response-headers/; https://docs.digitalocean.com/products/inference/details/availability/]
- [high] *digitalocean/app-platform*: BLR (Bangalore) is available for dynamic (container) apps; static sites in BLR are Cloudflare CDN only.
- Plans: apps-s-1vcpu-0.5gb $5/mo (fixed); apps-s-1vcpu-1gb-fixed $10; apps-s-1vcpu-1gb $12 (manually scalable); apps-d-1vcpu-0.5gb $29 (autoscaling).
- Billing is per second with a one-minute minimum, for the first 28 days of the month, so one day costs about $0.18 on the $5 plan. The free tier is static sites only.
- Scale-to-Zero bills at 10% while asleep, sleeps after 600–86,400 s idle, and wakes with a cold start of 'several seconds'.
- Images must be AMD64 Linux; under 1 GiB is recommended and over 2 GiB is risky. Builds time out after 1 h.
- Traffic goes through Cloudflare, HTTP/2 and HTTP/3 are downgraded to HTTP/1.1 at the container, the runtime is gVisor, and Docker Hub/GHCR images do not auto-redeploy.
- Health checks: health_check (readiness; HTTP if http_path is set, otherwise TCP) and liveness_health_check (restart). [evidence: https://docs.digitalocean.com/products/app-platform/details/availability/; https://docs.digitalocean.com/products/app-platform/details/pricing/; https://docs.digitalocean.com/products/app-platform/details/limits/; https://docs.digitalocean.com/products/app-platform/how-to/scale-to-zero/; https://docs.digitalocean.com/products/app-platform/how-to/manage-health-checks/]
- [low] *digitalocean/app-platform-streaming*: SSE and long requests on App Platform are uncertain. A 2021 community thread reports SSE events arriving all at once, and a 2023 thread cites a 100 s limit traced to Cloudflare. There is no official doc either way. Keep /ask non-streaming and test SSE before relying on it. [evidence: https://www.digitalocean.com/community/questions/feature-request-app-platform-supports-server-side-events (3P, 2021); https://www.digitalocean.com/community/questions/how-to-resolve-the-100s-request-timeout-of-digital-ocean-s-app-is-there-a-way-to-increase-the-timeout-or-something-else (3P, 2023)]
- [high] *providers/openai-compat-table*: OpenAI-compatible base URLs:
- OpenAI: https://api.openai.com/v1
- Gemini: https://generativelanguage.googleapis.com/v1beta/openai/
- Anthropic: https://api.anthropic.com/v1/
- Groq: https://api.groq.com/openai/v1
- Together: https://api.together.ai/v1
- Fireworks: https://api.fireworks.ai/inference/v1
- OpenRouter: https://openrouter.ai/api/v1
- DeepInfra: https://api.deepinfra.com/v1/openai
- Cerebras: https://api.cerebras.ai/v1
- Mistral: https://api.mistral.ai/v1
- DigitalOcean: https://inference.do-ai.run/v1
- Ollama: http://localhost:11434/v1/ (cloud: https://ollama.com/v1)
- vLLM: http://localhost:8000/v1
All stream and support tools.
Structured output: json_schema on OpenAI, Gemini, Groq (strict on select models), Cerebras (strict), Mistral (json_object and json_schema), Fireworks (JSON schema and grammar), Together, DeepInfra, Ollama, vLLM and OpenRouter (per model). Anthropic ignores response_format and strict. DO does not document it.
Embeddings: OpenAI, Gemini, Together, Fireworks, OpenRouter, DeepInfra (/v1/openai/embeddings), Mistral, DO, Ollama and vLLM. Not offered by Anthropic, Groq or Cerebras. [evidence: https://raw.githubusercontent.com/openai/openai-python/main/README.md; https://ai.google.dev/gemini-api/docs/openai; https://platform.claude.com/docs/en/api/openai-sdk; https://platform.claude.com/docs/en/build-with-claude/embeddings; https://console.groq.com/docs/openai; https://console.groq.com/docs/structured-outputs; https://docs.together.ai/docs/openai-api-compatibility; https://docs.fireworks.ai/tools-sdks/openai-compatibility; https://docs.fireworks.ai/structured-responses/structured-response-formatting; https://openrouter.ai/docs/quickstart; https://deepinfra.com/docs/openai_api; https://docs.deepinfra.com/apis/embeddings; https://inference-docs.cerebras.ai/resources/openai; https://inference-docs.cerebras.ai/capabilities/structured-outputs; https://docs.mistral.ai/api/; https://docs.ollama.com/openai; https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/]
- [high] *providers/anthropic-compat*: Anthropic's OpenAI SDK compatibility layer is 'not considered a long-term or production-ready solution'. stream and tools are supported. response_format and the strict flag are ignored, and prompt caching is not available through it. Forced tool_choice errors on Opus/Sonnet 5.5, Fable 5.1 and Mythos 5.1. Anthropic offers no embedding model and points to Voyage AI. [evidence: https://platform.claude.com/docs/en/api/openai-sdk; https://platform.claude.com/docs/en/build-with-claude/embeddings]
- [high] *pricing/cheap-models*: List prices per 1M tokens (input/output):
- OpenAI gpt-6-luna: $0.10/$0.50 (cached input $0.01, cache writes $0.125). gpt-5-nano $0.05/$0.40; gpt-5-mini $0.25/$2.00; gpt-5.4-nano $0.20/$1.25.
- Anthropic claude-haiku-5-5: $0.10/$0.50 for prompts up to 100K tokens ($0.50/$2.50 above).
- Groq openai/gpt-oss-120b $0.15/$0.60 (500 tok/s listed); gpt-oss-20b $0.075/$0.30 (1,000 tok/s). Llama 3.1 8B and 3.3 70B are now contact-sales.
- Cerebras gpt-oss-120b: $0.35/$0.75, about 3,000 tok/s.
- Fireworks gpt-oss-120b: $0.15/$0.60.
- Together gpt-oss-120B: $0.15/$0.60.
- Mistral Large: $0.5/$1.5. Ministral 8B is $0.15/$0.15 per OpenRouter (not first-party). [evidence: https://developers.openai.com/api/docs/pricing; https://platform.claude.com/docs/en/about-claude/pricing; https://platform.claude.com/docs/en/about-claude/models/overview; https://console.groq.com/docs/models; https://inference-docs.cerebras.ai/models/openai-oss; https://docs.fireworks.ai/serverless/pricing; https://www.together.ai/pricing; https://mistral.ai/pricing; measured: https://openrouter.ai/api/v1/models]
- [medium] *latency/artificial-analysis*: Artificial Analysis leaderboard medians (output tok/s; TTFT to first answer token; Intelligence Index):
- Gemini 3.5 Flash-Lite: 446; 6.98 s; 22.2
- Gemini 3.1 Flash-Lite: 368; 4.17 s; 15.6
- Gemini 3.8 Flash (High): 147; 23.6 s; 40.9
- Gemini 3 Flash Preview (non-reasoning): 200; 0.94 s; 17.9
- GPT-6 Luna (non-reasoning): 117; 0.94 s; 18.5 (Low: 120 tok/s, 2.14 s, 21.5)
- Claude Haiku 5.5 (Low): 183; 6.85 s; 29.5
- gpt-oss-120b (High), median across providers: 214; 10.2 s; 11.6. Per provider: Groq 474 tok/s with 0.71 s TTFT; Cerebras 1,729 tok/s with 0.42 s.
- Gemma 4 31B (non-reasoning): 49.6; 1.89 s; 13.9
Reasoning defaults dominate latency, so set reasoning_effort to low or minimal. [evidence: measured: parsed https://artificialanalysis.ai/leaderboards/models payload; measured: parsed https://artificialanalysis.ai/models/gpt-oss-120b/providers payload]
- [high] *pricing/cost-per-answer*: Cost for 4,000 input + 400 output tokens:
- Gemini 3.5 Flash-Lite $0.00220; 3.1 Flash-Lite $0.00160; 3.8 Flash $0.00450
- GPT-6 Luna $0.00060; GPT-5 nano $0.00036
- Claude Haiku 5.5 $0.00060
- Groq gpt-oss-120b $0.00084; Cerebras $0.00170
- DO: Gemma 4 31B $0.00092, gpt-oss-120b $0.00068, DeepSeek 4 Flash $0.00067
- DeepInfra Gemma 4 26B $0.00042; Workers AI Gemma 4 26B $0.00052; Together Gemma 4 31B $0.00195
- Gemma on the Gemini free tier: $0
Thinking tokens bill as output: adding 1,000 of them to Gemini 3.5 Flash-Lite gives $0.0047. [evidence: measured: scripts/cost.py using prices from https://ai.google.dev/gemini-api/docs/pricing, https://developers.openai.com/api/docs/pricing, https://platform.claude.com/docs/en/about-claude/pricing, https://console.groq.com/docs/models, https://inference-docs.cerebras.ai/models/openai-oss, https://docs.digitalocean.com/products/inference/details/pricing/, https://deepinfra.com/pricing, https://developers.cloudflare.com/workers-ai/platform/pricing/, https://www.together.ai/pricing]
- [high] *rate-limits/free-tiers*: Free tiers are too small for a scorer burst:
- Groq free plan, gpt-oss-120b: 30 RPM, 1K RPD, 8K TPM, 200K TPD (about 2 requests/min at 4k tokens). Developer plan: 1K RPM, 250K TPM.
- Cerebras free trial: 5 RPM, 30K uncached TPM, 1M TPD, 65K context. It is a $5 credit valid 30 days with a card required; there is no permanent free tier.
- Voyage Tier 1 (payment method required): 2,000 RPM.
- Jina: free key 100 RPM / 100K TPM.
- DO Tier 1: 120 RPM, 1.5M TPM. [evidence: https://console.groq.com/docs/rate-limits; https://console.groq.com/docs/models; https://inference-docs.cerebras.ai/support/rate-limits; https://inference-docs.cerebras.ai/models/openai-oss; https://docs.voyageai.com/docs/rate-limits; https://jina.ai/embeddings/; https://docs.digitalocean.com/products/inference/details/limits/]
- [high] *embeddings/api*: API embedding prices per 1M tokens:
- OpenAI text-embedding-3-small: 1536 dims, 8,192 tokens, $0.02, MTEB 62.3%.
- OpenAI text-embedding-3-large: 3072 dims, $0.13, MTEB 64.6%.
- Voyage voyage-4-lite / 4 / 4-large: $0.02 / $0.06 / $0.12; 1024 dims by default (256–2048), 32K context, first 200M tokens free.
- Cohere: pricing page shows no per-token API price; trial keys are rate-limited and not for production. A third-party source (June 2026) gives Embed 4 text at $0.12/1M.
- Jina embeddings v5 text (677M small / 239M nano, 32K context): sold in token packages; price not in the static page. [evidence: https://developers.openai.com/api/docs/guides/embeddings; https://developers.openai.com/api/docs/pricing; https://docs.voyageai.com/docs/pricing; https://docs.voyageai.com/docs/embeddings; https://cohere.com/pricing; https://developer.puter.com/tutorials/cohere-api-pricing/ (3P); https://jina.ai/embeddings/]
- [high] *embeddings/local*: Local models (dims; fastembed ONNX size; HF fp32 weights; MTEB Retrieval NDCG@10, classic English; license):
- bge-small-en-v1.5: 384; 0.067 GB; 133.5 MB; 51.68; MIT
- bge-base-en-v1.5: 768; 0.21 GB; 438 MB; 53.25; MIT
- nomic-embed-text-v1.5: 768; 0.52 GB (-Q 0.13 GB); 547 MB; 53.25 (per the Arctic card), MTEB avg 62.28; Apache-2.0; 8,192 tokens; needs prefixes
- snowflake-arctic-embed-s: 384; 0.13 GB; 133 MB (int8 34 MB); 51.98; Apache-2.0; needs prefixes
- snowflake-arctic-embed-m: 768; 0.43 GB; 436 MB; 54.90; Apache-2.0
- all-MiniLM-L6-v2: 384; 0.09 GB; 91 MB; 41.95; Apache-2.0; 256 tokens
- text-embedding-3-small, for comparison: 51.08 [evidence: measured: fastembed 0.9.0 TextEmbedding.list_supported_models() via uv run python -I; measured: https://huggingface.co/api/models/<id>?blobs=true; https://huggingface.co/BAAI/bge-small-en-v1.5 (README MTEB table); https://huggingface.co/Snowflake/snowflake-arctic-embed-s (README comparison tables); https://huggingface.co/nomic-ai/nomic-embed-text-v1.5]
- [medium] *embeddings/local-speed*: At low load on an Apple M5 Max with 2 threads, bge-small embeds 10.6 chunks/s (about 180-word chunks) and a single query in 2.3 ms at p50. Precompute corpus vectors offline and ship them as .npy. About 3k chunks would take roughly 5 minutes on 2 vCPU, too long for container startup. Under heavy contention (load average up to 83 from other agents) the same test gave 8.8 chunks/s, so treat contended numbers as noise. torch's linux wheel is 554.6 MB against 23.8 MB for onnxruntime, so prefer fastembed/ONNX over sentence-transformers. [evidence: measured: scripts/bench_embed2.py, notes/bench_embed_2threads_lowload.txt; measured: PyPI JSON wheel sizes, scripts/pypi_sizes.py]
- [high] *rerank/local*: fastembed TextCrossEncoder supports:
- Xenova/ms-marco-MiniLM-L-6-v2: 0.08 GB, Apache-2.0
- Xenova/ms-marco-MiniLM-L-12-v2: 0.12 GB, Apache-2.0
- BAAI/bge-reranker-base: 1.04 GB, MIT
- BAAI/bge-reranker-v2-m3: 2.27 GB (int8 0.57 GB), Apache-2.0
- jina-reranker-v1-tiny-en: 0.13 GB, Apache-2.0
- jina-reranker-v1-turbo-en: 0.15 GB, Apache-2.0
- jina-reranker-v2-base-multilingual: 1.11 GB, CC-BY-NC-4.0 (non-commercial)
FlashRank (Apache-2.0) offers TinyBERT-L-2 (~4 MB), MiniLM-L-12 (~34 MB), rank-T5-flan (~110 MB), MultiBERT-L-12 (~150 MB) and rank_zephyr_7b (~4 GB GGUF).
Measured p50 at low load, default threads:
- FlashRank TinyBERT: 13.9 ms for 20 candidates, 41.7 ms for 50
- fastembed MiniLM-L-6: 215 ms for 20 (303 ms at 2 threads), 863 ms for 50
- FlashRank MiniLM-L-12: 285 ms for 20, 1,176 ms for 50 [evidence: measured: fastembed TextCrossEncoder.list_supported_models(); https://raw.githubusercontent.com/PrithivirajDamodaran/FlashRank/main/README.md; measured: scripts/bench_rerank.py, notes/bench_rerank_lowload.txt]
- [medium] *rerank/api*: Rerank APIs:
- Voyage rerank-3: $0.05/1M tokens (about $0.0025 per request). rerank-3-lite: $0.02/1M. First 200M tokens free; tokens = query × docs + doc tokens.
- Cohere: a search is 1 query × up to 100 docs, and docs over 500 tokens are chunked and counted separately. Prices are third-party: Rerank 4 Fast $2.00 and Pro $2.50 per 1K searches.
- Jina jina-reranker-v3.5 (0.6B, 131K context): token-priced.
- DO BGE reranker: $0.01/1M, knowledge bases only. [evidence: https://docs.voyageai.com/docs/pricing; https://cohere.com/pricing; https://developer.puter.com/tutorials/cohere-api-pricing/ (3P); https://jina.ai/reranker/; https://docs.digitalocean.com/products/inference/details/pricing/]
- [medium] *retrieval/corpus-size*: olake.io corpus estimate: docs pages average 1,309 words (median 710) across 124 pages, about 162k words, which is 811 chunks at 200 words or 1,352 at 120. Blog pages average 3,390 words across 86 pages, about 292k words, or 1,458–2,429 chunks. The site totals roughly 2.3k–3.8k chunks before adding repo READMEs, issues and code docs. [evidence: measured: scripts/olake_sample.py, sampling 12 docs and 12 blog URLs from https://olake.io/sitemap.xml and counting article words; notes/olake_corpus_estimate.txt]
- [high] *retrieval/lexical-bench*: Lexical search, measured on 2k and 20k chunks of 180 words (index build / query p50):
- bm25s 0.3.13: 89 ms / 0.02 ms and 923 ms / 0.10 ms
- tantivy-py 0.26.2: 422 ms / 0.05 ms and 400 ms / 0.13 ms
- SQLite FTS5 bm25() (stdlib, sqlite 3.50.4): 27 ms / 0.40 ms and 264 ms / 3.5 ms
- rank_bm25 0.2.2: 62 ms / 0.97 ms and 659 ms / 13.8 ms
Published: BM25S reports 1,196 QPS against rank-bm25's 225 on nfcorpus, and 953 against 47.6 on scifact (single-threaded Xeon). [evidence: measured: scripts/bench_lexical.py, notes/bench_lexical.txt; https://raw.githubusercontent.com/xhluca/bm25s/main/README.md]
- [high] *retrieval/vector-bench*: Vector search on random unit vectors, query p50 at 2k / 20k with 384 dims (768 dims at 20k in brackets):
- numpy brute force: 0.026 / 0.35 ms (0.68)
- FAISS IndexFlatIP 1.15.1: 0.041 / 0.24 ms (0.33)
- hnswlib 0.8.0: 0.18 / 0.39 ms, build 2.0 s, poor recall on random vectors
- sqlite-vec 0.1.9: 0.14 / 1.40 ms (2.57)
- Chroma 1.5.9: 0.71 / 1.31 ms, build 3.0 s
- LanceDB 0.40.0 flat: 1.23 / 3.71 ms
Published: sqlite-vec is brute-force only; on SIFT1M (k=20) the reported averages are FAISS 10 ms, sqlite-vec static 17 ms, vec0 33 ms, numpy 136 ms (M1, 2024-08, possibly stale).
hnswlib ships only an sdist, so it needs a compiler in Docker. [evidence: measured: scripts/bench_vector.py, notes/bench_vector.txt; https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html; measured: PyPI JSON via scripts/pypi_sizes.py]
- [high] *retrieval/services*: Hosted vector services add a network hop and inactivity-pause risk:
- Qdrant Cloud free: 0.5 vCPU / 1 GB RAM / 4 GB disk; suspended after 1 week unused, deleted after 4 weeks.
- Supabase free: 500 MB database; paused after 1 week of inactivity; 2 active projects.
- Neon free: 100 CU-hrs per project per month; scales to zero after 5 minutes.
- Pinecone: Starter is free; Builder is $20/month.
- Cloudflare Vectorize free: 30M queried and 5M stored dimensions per month; max 1536 dims. [evidence: https://qdrant.tech/pricing/; https://qdrant.tech/documentation/cloud/create-cluster/; https://supabase.com/pricing; https://neon.com/pricing; https://www.pinecone.io/pricing/; https://developers.cloudflare.com/vectorize/platform/pricing/; https://developers.cloudflare.com/vectorize/platform/limits/]
- [high] *hosting/cloud-run*: Cloud Run, asia-south1 (Mumbai) and asia-south2 (Delhi), with asia-south1 at Tier 1 pricing:
- Request-based billing: CPU $0.000024/vCPU-s and memory $0.0000025/GiB-s active; idle min-instance CPU and memory each $0.0000025; requests $0.40/M.
- Free tier: 180k vCPU-s, 360k GiB-s and 2M requests, applied as a spend discount.
- Instance-based billing: $0.000018/vCPU-s and $0.000002/GiB-s.
- Request timeout defaults to 5 min, maximum 60 min.
- Min instances are best-effort.
- Startup, liveness and readiness probes support HTTP, TCP and gRPC; HTTP probe endpoints are externally reachable.
- Streaming responses are supported via Transfer-Encoding: chunked. HTTP/2 is downgraded to HTTP/1 by default.
- Structured JSON logs land in jsonPayload, with trace correlation via X-Cloud-Trace-Context.
- Computed: min-instances=1 at 1 vCPU / 512 MiB costs about $0.32/day idle, or about $9.7 per 30 days before the free-tier offset (up to about $5.2). [evidence: https://cloud.google.com/run/pricing; https://cloud.google.com/run/docs/configuring/request-timeout; https://cloud.google.com/run/docs/configuring/min-instances; https://cloud.google.com/run/docs/locations; https://cloud.google.com/run/docs/configuring/healthchecks; https://cloud.google.com/run/docs/triggering/https-request; https://cloud.google.com/run/docs/logging]
- [high] *hosting/fly*: Fly.io:
- Smallest always-on machine is $2.19/month; shared-cpu-1x 512 MB is $3.69/30 days at iad/ewr prices (other regions differ).
- A stopped machine bills only rootfs at $0.15/GB/month.
- New-org free trial is only 2 hours of machine runtime or 7 days, whichever comes first, then a card is needed.
- No India region exists; Singapore (sin) is nearest. India/Africa egress is $0.12/GB.
- Autostop cold start is about 2 s or more.
- Health checks via [[http_service.checks]] with grace_period, interval and path; 2xx required and redirects are not followed.
- Fly-Client-IP header provided; X-Forwarded-For can be spoofed. [evidence: https://fly.io/docs/about/pricing/; https://fly.io/docs/reference/regions/; https://fly.io/docs/launch/autostop-autostart/; https://fly.io/docs/reference/configuration/; https://fly.io/docs/networking/request-headers/]
- [high] *hosting/render-railway-koyeb*: Render:
- Free web services spin down after 15 minutes without traffic, take about a minute to spin up, and show a loading page to browsers; not for production.
- Starter is $7/month (0.5 CPU, 512 MB), prorated per second; 1 CPU / 2 GB is $25.
- Regions: Oregon, Ohio, Virginia, Frankfurt, Singapore.
- Health checks need 2xx/3xx within 5 s, and a deploy is cancelled if it is not healthy within 15 minutes.
Railway:
- Trial is a one-time $5. Free plan gives $1/month with 0.5 GB RAM.
- Hobby is $5/month including $5 of usage, billed at $20/vCPU-month and $10/GB-month.
- Has a Singapore region. Serverless mode sleeps after 5 minutes without outbound packets.
Koyeb:
- Free instance is 0.1 vCPU / 512 MB, Frankfurt or Washington only, and scales to zero after 1 hour.
- Pro is $29/month plus compute; nano is $2.68 and micro $5.36; eco instances exist in Singapore.
- Site banner: 'Koyeb is joining Mistral AI'. [evidence: https://render.com/docs/free; https://render.com/pricing; https://render.com/docs/regions; https://render.com/docs/health-checks; https://docs.railway.com/reference/pricing/plans; https://docs.railway.com/reference/deployment-regions; https://docs.railway.com/reference/app-sleeping; https://www.koyeb.com/pricing; https://www.koyeb.com/docs/reference/instances; https://www.koyeb.com/docs/reference/regions]
- [high] *hosting/hf-spaces*: Hugging Face Spaces:
- Creating Docker or Gradio Spaces now requires a paid plan (PRO is $9/month); static Spaces stay free.
- CPU Basic is free: 2 vCPU, 16 GB RAM, 50 GB non-persistent disk. It sleeps after 48 hours inactive and restarts on visit. CPU Upgrade (8 vCPU / 32 GB) is $0.03/hour.
- URL format is https://<space-subdomain>.hf.space; app_port defaults to 7860; startup_duration_timeout defaults to 30 minutes; only COEP/COOP/CORP custom headers are allowed.
- A live hf.space app returned no X-Frame-Options or CSP and echoed the Origin on CORS preflight, so the app itself controls CORS. [evidence: https://huggingface.co/docs/hub/spaces-overview; https://huggingface.co/docs/hub/spaces-gpus; https://huggingface.co/pricing; https://huggingface.co/docs/hub/spaces-sdks-docker; https://huggingface.co/docs/hub/spaces-embed; https://huggingface.co/docs/hub/spaces-config-reference; measured: curl -D and OPTIONS against https://nimaboscarino-hotdog-gradio.hf.space/ (URL taken from HF docs)]
- [high] *hosting/vercel-cloudflare*: Vercel:
- Python functions are ASGI/WSGI (FastAPI supported).
- Bundle limit is 250 MB, or 500 MB for Python (up to 5 GB with large functions in beta).
- Max duration: 300 s on Hobby; 800 s on Pro (1800 s beta).
- Default region iad1; bom1 (Mumbai) can be selected.
- Hobby is personal, non-commercial use only.
Cloudflare Workers:
- Free: 100K requests/day, 10 ms CPU per request, 128 MB memory, 64 MiB worker size, 1 s startup.
- Paid: $5/month minimum.
- Python needs the python_workers compatibility flag.
- Workers AI: 10K neurons/day free, $0.011 per 1K neurons; bge-small at $0.020/1M.
- 10 ms CPU rules out in-Worker Python BM25. [evidence: https://vercel.com/docs/functions/limitations; https://vercel.com/docs/functions/runtimes/python; https://vercel.com/pricing; https://vercel.com/docs/regions; https://developers.cloudflare.com/workers/platform/limits/; https://developers.cloudflare.com/workers/platform/pricing/; https://developers.cloudflare.com/workers/languages/python/; https://developers.cloudflare.com/workers-ai/platform/pricing/]
- [high] *hosting/tunnels*: Cloudflare quick tunnels (trycloudflare) are for testing only:
- random URL
- no uptime guarantee
- 200 in-flight requests, then 429
- no Server-Sent Events
ngrok free tier:
- one assigned dev domain that persists
- 1 GB/month data, 20,000 HTTP requests/month, 4,000/min, 3 endpoints
- an interstitial on HTML browser traffic only; APIs and programmatic access are unaffected, and the ngrok-skip-browser-warning header bypasses it [evidence: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/; https://ngrok.com/docs/pricing-limits/free-plan-limits/]
- [high] *widget/vendor-patterns*: Docs-AI vendors use a script tag, Shadow DOM and fetch streaming:
- kapa.ai: single async script widget.kapa.ai/kapa-widget.bundle.js with data-* attributes; Docusaurus via the scripts config. Bundle is 2.13 MB raw / 605 KB compressed and uses attachShadow mode open (no iframe). It streams via body.getReader to proxy.kapa.ai, uses reCAPTCHA/hCaptcha and a server-side domain allowlist, and includes aria-live and aria-modal.
- Inkeep: script from cdn.jsdelivr.net/npm/@inkeep/cxkit-js@0.5/dist/embed.js plus Inkeep.ChatButton with a client-side apiKey. Bundle is 1.66 MB, with attachShadow, getReader and aria-live.
- DocsBot: async loader DocsBotAI.init({id}); floating, or inline in #docsbot-widget-embed.
Support-chat widgets differ:
- Intercom: needs CSP child-src/frame-src (iframes) plus connect-src including wss.
- Crisp: needs style-src 'unsafe-inline', worker-src blob:, img-src data: and wss relays. [evidence: https://docs.kapa.ai/integrations/website-widget/installation/docusaurus; https://docs.kapa.ai/integrations/website-widget/quickstart; measured: grep of downloaded https://widget.kapa.ai/kapa-widget.bundle.js (not executed); https://docs.inkeep.com/ui-components/js-snippet/chat-button; measured: grep of https://cdn.jsdelivr.net/npm/@inkeep/cxkit-js@0.5/dist/embed.js; https://docsbot.ai/documentation/developer/embeddable-chat-widget; https://www.intercom.com/help/en/articles/3894-using-intercom-with-content-security-policy; https://docs.crisp.chat/guides/others/whitelisting-our-systems/crisp-domain-names/]
- [high] *widget/olake-site*: olake.io/docs is Docusaurus v3.10.2 served by GitHub Pages behind Fastly (Chennai POP, cache-control max-age=600). It has no Content-Security-Policy header or meta tag and no X-Frame-Options, and uses Algolia DocSearch. It ships /message-listener.js, which accepts postMessage {theme: light|dark} from a parent window when the docs are embedded in an iframe. So a script widget will load, it should follow html[data-theme], and it must work inside iframes. [evidence: measured: curl -D https://olake.io/docs/ and HTML grep (meta generator, script tags); measured: https://olake.io/message-listener.js]
- [high] *widget/docusaurus*: Docusaurus integration options:
- scripts: inserted in head; render-blocking unless async or defer is set.
- headTags: tagName and attributes, e.g. preconnect to the API.
- clientModules: global JS/CSS loaded before React renders. They also run during SSR, so guard with ExecutionEnvironment.canUseDOM; onRouteDidUpdate hook available.
- Swizzled src/theme/Root.js: top of the React tree and never unmounts, so it suits a stateful React widget. [evidence: https://docusaurus.io/docs/api/docusaurus-config; https://docusaurus.io/docs/advanced/client; https://docusaurus.io/docs/swizzling]
- [high] *widget/cors-csp-a11y*: CORS: application/json is not a CORS-safelisted content type, so every widget POST is preflighted. Answer OPTIONS with Allow-Origin/Methods/Headers and Max-Age; with credentials, the * wildcard is not allowed.
CSP: a strict host page must allow the widget in script-src and the API in connect-src; frame-src only if using an iframe; style-src if inline styles are injected.
Accessibility:
- role=log is implicitly aria-live polite.
- Set aria-busy while streaming so screen readers announce once.
- Use role=dialog with aria-labelledby.
- Move focus into the dialog on open and restore it on close; tab order should wrap.
EventSource only takes a URL plus withCredentials, so it cannot POST; use fetch with ReadableStream. [evidence: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS; https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP; https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/log_role; https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions; https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/dialog_role; https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events]
- [high] *ops/sse*: FastAPI 0.135.0+ has native SSE (fastapi.sse.EventSourceResponse, POST supported). It sends a keep-alive ping every 15 s and sets Cache-Control no-cache and X-Accel-Buffering no; the latest release is 0.143.3. sse-starlette is the alternative (ping default 15 s, send_timeout, disconnect detection). nginx honours X-Accel-Buffering. In a local POC the stream returned text/event-stream, no-cache, x-accel-buffering: no and chunked encoding, and a Node client parsed 25 events with the first delta at 37 ms. [evidence: https://fastapi.tiangolo.com/tutorial/server-sent-events/; https://raw.githubusercontent.com/sysid/sse-starlette/main/README.md; https://nginx.org/en/docs/http/ngx_http_proxy_module.html; measured: poc/app.py run locally plus curl; poc/widget/test-client.mjs (Node 24)]
- [high] *ops/rate-limit*: slowapi (the flask-limiter port, e.g. @limiter.limit('5/minute')) describes itself as 'alpha quality code'. A 20-line in-memory token bucket works: the POC with burst 5 at 0.5 requests/s returned 200 200 200 429 with retry-after and a contract-shaped body. The default FastAPI 422 validation body {detail} does not match the {answer, sources} contract, so add exception handlers. [evidence: https://slowapi.readthedocs.io/en/latest/; measured: poc/app.py local curl burst test]
- [high] *ops/retries-timeouts*: OpenAI Python SDK defaults: 2 retries with short exponential backoff on connection errors, 408, 409, 429 and 5xx; timeout 10 minutes; streams are not retried automatically. The SDK now uses httpx2. tenacity provides stop_after_attempt, wait_exponential and jitter. DeepInfra offers fail_fast, which returns 429 instead of queueing. [evidence: https://raw.githubusercontent.com/openai/openai-python/main/README.md; https://tenacity.readthedocs.io/en/latest/; https://deepinfra.com/docs/openai_api]
- [high] *ops/prompt-caching*: Provider prompt caching:
- OpenAI (GPT-5.6 and later): caching is automatic, with a minimum prefix of 1,024 tokens. Writes cost 1.25x, reads 0.1x (0.05x on GPT-6.1 Sol), and TTL is at least 30 minutes.
- Gemini: implicit caching is on by default for 2.5 and newer. Minimum prefix is 4,096 tokens for 3.8 and 3.6 Flash and 2,048 for 2.5 Flash; Flash-Lite is not listed.
- Anthropic: minimum is 512 tokens for Haiku 5.5. Writes cost 1.25x for 5 minutes or 2x for 1 hour, reads 0.1x. Caching is not available via the OpenAI-compat layer.
- DigitalOcean: Gemma 4 cache read is $0.036 versus $0.18.
In RAG only the static prefix is reusable: a 1.5k-token static prefix on gpt-6-luna saves about $0.000135 per answer (about 22%), and typical prompts will not reach Gemini 3.8's 4,096-token minimum. An app-level answer cache saves far more. [evidence: https://developers.openai.com/api/docs/guides/prompt-caching; https://ai.google.dev/gemini-api/docs/caching; https://platform.claude.com/docs/en/build-with-claude/prompt-caching; https://platform.claude.com/docs/en/about-claude/pricing; https://docs.digitalocean.com/products/inference/details/pricing/]
- [high] *ops/container-footprint*: POC images built on Docker Desktop (arm64, run with --cpus=1 --memory=1g, loading a 3,000-chunk BM25 index at startup):
- Lean (python:3.12-slim with fastapi, uvicorn, openai, numpy, bm25s): 73 MB compressed, ready in 1.28 s (app startup 0.53 s), 59 MiB idle RSS.
- Local-embed (adds fastembed and a baked bge-small): 180 MB compressed, ready in 1.24 s, 189 MiB.
Both fit in 512 MiB plans. Local builds took 9 s and 24 s with a cached base image. [evidence: measured: docker build/save|gzip/run/stats with poc/img/Dockerfile.lean and Dockerfile.local (images deleted afterwards)]
- [high] *network/latency*: From this IST machine, warm HTTPS medians to gcping Cloud Run endpoints were: asia-south1 Mumbai 41.5 ms, asia-south2 Delhi 53.4 ms, asia-southeast1 Singapore 53.0 ms, us-central1 261.7 ms, europe-west1 360.2 ms, us-east1 387.9 ms. TCP connect to LLM API edges (Gemini, OpenAI, Anthropic, Groq, Cerebras, OpenRouter, Together, DO) took 6–21 ms, but DeepInfra took about 258 ms (direct to origin), so reuse connections. The DO speedtest hostnames no longer resolve. [evidence: measured: scripts/ping_regions.py over https://gcping.com/api/endpoints (notes/gcping_latency.txt); measured: curl -w time_connect x3 (notes/provider_rtt.txt); measured: dig speedtest-{blr1,sgp1,fra1,nyc3}.digitalocean.com returned no answer]
- [high] *deps/wheel-sizes*: Linux x86_64 wheel sizes from PyPI:
- fastapi 0.143.3 and uvicorn 0.54.0: about 0.1 MB each
- openai 3.31.0: 2.2 MB
- litellm 1.105.1: 38.8 MB
- numpy 2.5.4: 16.7 MB
- bm25s: 0.1 MB
- tantivy: 4.5 MB
- faiss-cpu: 18.8 MB
- sqlite-vec: 0.2 MB
- lancedb: 75.2 MB, plus pyarrow 53.9 MB
- chromadb: 23.3 MB plus dependencies
- onnxruntime: 23.8 MB
- torch 2.14.1: 554.6 MB
- hnswlib 0.8.0: sdist only [evidence: measured: scripts/pypi_sizes.py against https://pypi.org/pypi/<pkg>/json (notes/pypi_sizes.txt)]

## Open questions
- Which 'LLM API credits' does the event actually hand out (provider, amount, tier)? The MLH DigitalOcean signup link redirects to the DO homepage and DO docs mention only a $5 signup credit. Is a DO promo code or Gemini credit given at the venue?
- Do gemma-4-31b-it and gemma-4-26b-a4b-it work through https://generativelanguage.googleapis.com/v1beta/openai/ with stream:true and response_format? It is undocumented; Artificial Analysis marks AI Studio Gemma as OpenAI-compatible.
- What are the real Gemini free-tier RPM/RPD for the team's project (visible only in AI Studio)? A third-party snapshot says Gemma 4 has 15 RPM / 1,500 RPD and 'Gemini 3.5 Flash' 20 RPD.
- How many questions are in the hidden test set, and are they sent concurrently from one IP? This sets per-IP limits, the global semaphore and the provider quota needed.
- Does DigitalOcean App Platform buffer SSE or cap requests at 100 s today? Only 2021 and 2023 community threads exist.
- Will a GCP billing account be available on the day (Cloud Run requires one), or only DO credits?
- Does the operator want Gemma 4 as the generator for the open-weight story? It takes about 9–12 s for a 400-token answer at 35–47 tok/s on AI Studio or DO, against about 1–4 s for gpt-oss-120b on Groq or Cerebras or GPT-6 Luna non-reasoning.
- Does a reranker or an API embedding model (gemini-embedding-2, voyage-4-lite) measurably beat local bge-small plus BM25 on the OLake eval set? Decide by eval.
- Exact gemini embedding model ID on the OpenAI-compat path: gemini-embedding-2 (embeddings page) or gemini-embedding-2-preview (OpenAI-compat page)?

## Report path note
NOT WRITTEN. The harness rejected the write ('Subagents should return findings as text, not write report files'); the full report is in this return. Intended path: (probe script in a deleted scratch dir) Kept artifacts in the same folder: notes/*.txt (raw measurement outputs), scripts/*.py (benchmarks and parsers), poc/app.py (FastAPI contract API with CORS, SSE, token bucket, request IDs), poc/widget/{widget.js,ask-client.js,test-client.mjs}, poc/img/Dockerfile.{lean,local}. Deviations: about 1 GB downloaded against the 600 MB budget, all deleted; gh api against datazip-inc repos was denied; nothing was written to the worktree.
