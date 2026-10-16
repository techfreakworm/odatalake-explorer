# Ask OLake: research, comparisons and decisions

Status: draft, filled in as the research reports and POC measurements land. `PENDING(x)` marks a section or number that
waits on input x. Measured numbers name their source file, and unmeasured goals are labelled **target**.
The runbook that carries out these decisions is [plan.md](plan.md). Open items are in [open-questions.md](open-questions.md).

## 1. Executive summary

1. **Deliverable**: a public `POST /ask` (`{"question"}` in, `{"answer", "sources"}` out), an embeddable chat UI, and a repo
   with a README on architecture and design choices ([challenges page][ch]).
2. **Corpus** (§3): tier 1 is the 124 `/docs/` pages from the rendered HTML minus a denylist of stub pages, plus GitHub
   release notes, the two product FAQs and fact cards generated at the event. Tier 2 is a Tier A repo allowlist and 10
   curated issues. Tier 3 is the blog, decided by an A/B run at the event (D4). Tier 4 is about 23 curated outside pages,
   labelled. Not indexed: upstream Amoro docs (D11), bulk issues, discussions.
3. **Citations** (§3.5): `sources` holds canonical sitemap URLs (trailing slash, no anchor), capped at 5. For repo files,
   `SOURCE_URL_STYLE` switches between branch-form and SHA-permalink GitHub URLs (K3). Anchors and line ranges appear in
   the UI.
4. **Architecture**: hybrid retrieval (BM25 plus local dense embeddings, RRF k=60), a local cross-encoder rerank, then one
   grounded LLM call with `[n]` citations, behind two gates and three logged abstain triggers. The fallback is BM25-only
   with the same chunks and prompt, behind a config flag (§4).
5. **Stack**: Python 3.12, FastAPI, the `openai` SDK pointed at any OpenAI-compatible endpoint, fastembed (ONNX, CPU) for
   embeddings and reranking, bm25s, and numpy brute-force vectors. One container. PENDING(stack report: host, model, prices) (§5).
6. **Widget**: a small `widget.js` loader that injects a launcher and an iframe served from our origin (`/embed`), plus a plain
   iframe snippet and a Docusaurus `scripts` snippet (§5.6).
7. **Freshness** (§3.6): poll the sitemap with `If-None-Match`. On a deploy, re-fetch all docs (about 2 s), hash and re-embed
   only changed chunks. For repos, `git ls-remote` plus the compare API. olake.io's ETags, Last-Modified and `lastmod`
   are not content signals.
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
| Default rules (MLH) | The event pages publish no event-specific rules. MLH's standard hackathon rules, which organizers may adopt or modify, say: all project work happens during the hackathon; an earlier idea is fine but its code and other project materials may not be re-used; libraries and open-source code are fine, but a project built beforehand and open-sourced just to use at the event is not; stop at time-up, with small fixes allowed and no new features; code must be public and stay public; AI coding tools are allowed but must be disclosed. The MLH organizer guide also asks for frameworks to be listed in the README | [MLH rules][mlh], [MLH organizer guide][mlh-guide]; see K5, K6 and D2 in [open-questions.md](open-questions.md) |

Implication (inference, not stated anywhere): scoring runs after 14:30 and before the 15:30 top-10 announcement, against
the live endpoint. So the service must stay up, warm and rate-limit-tolerant in that window and through the demos until 17:00.

## 3. Corpus

Sources for this section: the doc-writer's own checks, the POC results (`poc/results/*.json`), and three research runs from
2026-10-16 that the lead condensed into the corpus decisions. They are the **[docs-site report][r-docs-site]**, the **[repos report][r-repos]** and
the **[olake-domain report][r-olake-domain]**. Sanitized copies of all reports are committed under `docs/reports/`, with paths to
deleted scratch scripts replaced. A number from a report names the report and its method, and an evidence URL from a report is
cited directly.

### 3.1 Docs site

| Measurement | Value | Source |
|---|---|---|
| Platform | Docusaurus v3.10.2 on GitHub Pages behind a CDN (`server: GitHub.com`, `via: 1.1 varnish`, `x-served-by: cache-maa…`, `cache-control: max-age=600`). One docs plugin instance with two sidebars (OLake Go and Fusion); no versioning, no i18n, no CSP header | [docs-site][r-docs-site] and [olake-domain][r-olake-domain] reports (curl -I, generator meta); headers re-checked by the doc-writer |
| Site search | Algolia DocSearch. No AI assistant is configured (DocSearch "Ask AI" is in the bundle but off), so the judges' everyday baseline is keyword search | [docs-site report][r-docs-site] |
| Sitemap | 275 URLs: 124 under `/docs/` (101 OLake Go, 23 Fusion), 86 under `/blog/` (85 posts and the index), 65 others. 231 carry `lastmod`. All 275 end with `/` | The doc-writer counted `<loc>` entries in [the sitemap][sitemap] at 2026-10-16T17:14Z; the Go/Fusion split is from the [docs-site report][r-docs-site] |
| Release notes | 24 pages under `/docs/release/` and 2 under `/docs/fusion/release/` | Sitemap count; `poc/results/corpus.json` |
| Docs size | 238,135 o200k tokens from article text ([docs-site report][r-docs-site], `measure_corpus.py`), or 263,614 from the POC's Markdown, which keeps code and table syntax (`poc/results/corpus.json`). 830 code blocks, 182 tables, 80 tab groups with 202 panels (122 hidden at load), 342 admonitions. The largest page is [the REST catalog page][rest] | [docs-site report][r-docs-site]; `poc/results/corpus.json` |
| Thin pages | 13 pages under 100 tokens (7 of them among the 23 Fusion pages), per the POC. The [docs-site report][r-docs-site] counts about 15 stub or stale pages, and the [olake-domain report][r-olake-domain] counts 18 pages under 1,300 characters | `poc/results/corpus.json`; both reports |
| Fetch cost | All 124 pages in 3.9 s (11.17 MB uncompressed), or 2.2 s and 2.07 MB with gzip, 4 at a time ([docs-site report][r-docs-site]). The POC took 7.52 s at concurrency 4 | [docs-site report][r-docs-site]; `poc/results/corpus.json` |
| Blog | 85 posts: 428,473 o200k tokens from article text ([docs-site report][r-docs-site]), or 446,137 from the POC's Markdown | [docs-site report][r-docs-site]; `poc/results/corpus.json` |

**Decision: rendered HTML, not raw MDX.** Raw MDX misses content on 22 of the 124 docs pages: every connector main page,
every catalog page, the Parquet writer pages, docker-cli and commands-and-flags. That content comes from 92 globally
registered MDX partials, 12 JSX config-table components, `FlagDetail.tsx` (CLI flags) and `DateTimeHandling.tsx`, all
registered in the site's [MDX component map][mdx-map]. For example, the Postgres `jsonb` to Iceberg `string` mapping exists
only in a partial and in the rendered HTML. The rendered HTML is complete: all 202 tab panels are server-rendered
([docs-site report][r-docs-site]). Extraction selectors: `.theme-doc-markdown` for docs and `#__blog-post-container` for posts.

**No shortcuts.** [llms.txt][llms] is a hand-written link index with no page bodies (22,607 bytes, 152 lines). The
site's `/llms-full.txt`, `.md` page URLs and `search-index.json` all return 404 ([docs-site report][r-docs-site]; the doc-writer
re-checked `/llms-full.txt` on 2026-10-16).

**Traps the index has to handle.**
- **Stale or stub pages.** About 15-18 of them. Two contradict live pages: `/docs/connectors/overview/` and
  `/docs/connectors/kafka/overview/` still call Kafka "WIP" or "coming soon", while [the Kafka connector page][kafka] is
  live. Decision: a denylist, excluded from the index and logged (plan Appendix A).
- **Twin pages.** OLake Go and Fusion pages are 0.95-1.00 similar, with identical titles. One example pair:
  [Go offline AWS install][go-aws] and [Fusion offline AWS install][fus-aws]. Ten pages share the H1 "Overview". Decision:
  every chunk carries `product`, and the context header reads "title | product > breadcrumbs > heading path [tab label]"
  ([docs-site report][r-docs-site]).
- **Naming.** "OLake Go" has been the ingestion product's name since the 2026-06-14 docs restructure (olake-docs commit
  5978892, [docs-site report][r-docs-site]). OLake, OLake Go and OLake ingestion are synonyms.
- **The docs lag GitHub.** The docs release notes stop at [v0.12.0][rel-0120], while [GitHub releases][olake-rel] show olake
  v0.12.1 and olake-ui v0.7.1 (2026-10-15). Docs release-note pages appear 3-9 days after the GitHub release: v0.8.0 after 5
  days, v0.9.0 6, v0.10.0 9, v0.11.0 3, v0.12.0 5 ([olake-domain report][r-olake-domain]).
- **First-party contradictions.** The [olake-domain report][r-olake-domain] lists 10 and the [eval-ops report][r-eval-ops] 9. The clearest is Fusion's
  default compaction schedule: 1h/8h/never on [configure first compaction][fus-first], 24h each on
  [compaction configuration][fus-conf], and 20m/40m (benchmark values) in the [Fusion product FAQ][fus-faq]. Others: the
  [MySQL page][mysql] example uses `initial_wait_time` 10 while the driver enforces a 120 s minimum, and
  `binlog_row_metadata=FULL` is listed as required although it has been optional since [v0.10.0][rel-0100] (eval-ingestion
  report). Decision: when OLake pages disagree, the answer cites both and says so.

### 3.2 Repositories

| Repo | HEAD (2026-10-16 snapshot) | Files at HEAD | Releases in the last 6 months / latest | License |
|---|---|---|---|---|
| olake | d20c68e (2026-10-15) | 450 | 27 / v0.12.1 (2026-10-15) | Apache-2.0 |
| olake-ui | 56826cf (2026-10-15) | 519 | 16 / v0.7.1 (2026-10-15) | Apache-2.0 |
| olake-helm | c63f10c (2026-10-08) | 123 | 23 / worker v0.4.0 and chart olake-0.0.30 (2026-10-08) | Apache-2.0 |
| olake-fusion | 15ca160 (2026-10-13) | 2,315 | 4 / v0.1.4 (2026-08-24) | Apache-2.0 |

Sources: the [repos report][r-repos] (tree and releases APIs); `poc/results/corpus.json` (SHAs and branch `master`); licenses and the
`fork` flag from the GitHub API (checked by the doc-writer).

**Decision: Tier A allowlist only** (about 94K tokens, 377,136 bytes, against about 24 MB for a naive crawl of every text
file; [repos report][r-repos]). The exact list is in plan Appendix A. The highest-value files:
- `drivers/*/resources/spec.json` and the Iceberg and Parquet writer specs. These JSON Schemas drive the UI forms, and
  converting them to Markdown field tables cuts 118,870 bytes to 39,612.
- [`protocol/root.go`][rootgo]: 5 commands and 16 persistent CLI flags.
- [helm `values.yaml`][values]: 65% of its non-blank lines are comments.
- The olake-ui `docker-compose-v1.yml` quickstart.
- olake-fusion's [`CLAUDE.md`][fus-claude]: Lite/Medium/Full map to minor/major/full; it also gives the default schedules,
  the 512 MB target file size and the Iceberg-only scope.

The POC used a broader allowlist (84 files, 143,596 tokens, `poc/results/corpus.json`), with more Go config structs.
The event uses the reports' Tier A list.

**[olake-fusion][fusion-repo] is a modified hard fork of [Apache Amoro][amoro].** The evidence: its [NOTICE][fus-notice] and DISCLAIMER, the pom
parent `org.apache.amoro:amoro-parent:0.9-SNAPSHOT`, 119 files headed "Modified by Datazip", and 1,851 imported upstream
commits ([repos report][r-repos]). GitHub does not flag it as a fork. Its `docs/` and `site/` folders are upstream Amoro and are not
indexed, because their defaults contradict Fusion's. Snapshot expiry (`table-expire.enabled`) is off in Fusion but on
upstream, and the target file size is 512 MB in Fusion against 128 MB in [Amoro's configuration docs][amoro-conf]
([repos][r-repos] and [olake-domain][r-olake-domain] reports). Amoro concepts enter only through labelled outside pages (§3.4).

**Issues and discussions: curated, not bulk.** About a third of the olake issues are bot TODOs (99 of 321). The docs team
copies fixes into the docs, and Discussions has 7 threads with one unanswered Q&A ([repos report][r-repos]). The index takes 10
troubleshooting answers that were checked absent from the docs (list in plan Appendix A), each cited as "known issue #N".

**Default credentials** appear in the olake-ui README and compose file, and in the helm values (`initUser`,
`postgresql.auth`, `minio.auth`). They are redacted in chunks, and the bot states only what the docs state ([repos report][r-repos]).

### 3.3 Other first-party sources

- **GitHub release notes**: the last ~10 per repo, cited as `releases/tag/<tag>`. They are newer than the docs (§3.1). About
  31.5K tokens in total ([repos report][r-repos]).
- **Product FAQs**: FAQPage JSON-LD on [/olake-go/][go-faq] (enterprise plans via hello@olake.io, Apache-2.0 licensing,
  integrations) and on [/olake-fusion/][fus-faq] (standalone use, compaction cadence, licensing, target size). Both
  answer pre-sales questions the docs do not ([olake-domain report][r-olake-domain]).
- **Fact cards**: short documents generated at the event from the fetched docs, each citing the canonical pages it came
  from: a source × sync-mode matrix with explicit negatives (Oracle and DB2: no CDC; Kafka: `strict_cdc` only; S3: full
  refresh and incremental, append-only), destination × catalog × minimum version, feature → minimum component versions,
  latest versions, unsupported or undocumented items, and known contradictions. Why: in the [olake-domain report][r-olake-domain]'s BM25
  test on 35 answerable seed questions, capability questions such as "Oracle CDC?" retrieved old release notes, because the
  Oracle page never says "no CDC". Page-level hit@1/3/5 was 18/26/29 and chunk-level 22/26/30. Chunk-level plus three
  rules gave 27/28/32: demote old release notes x0.3, boost the named connector page x1.6, and a synonym map.

### 3.4 Outside sources

Allowed by the challenge "when the docs fall short" ([challenges page][ch]). The [olake-domain report][r-olake-domain] opened and
classified about 23 pages: Iceberg maintenance, procedures and spec; Amoro self-optimizing and configurations; PostgreSQL
replication, logical decoding and `ALTER TABLE`; the MySQL binlog options; the MongoDB oplog and change streams; SQL Server
CDC; Kafka consumer configs and operations; S3 Tables, Databricks Unity, Athena, Lakekeeper, Polaris, Nessie, BigLake,
Snowflake Horizon; and Temporal. The exact URLs are in plan Appendix A. Rule: OLake docs decide what OLake requires, and
vendor docs explain how their own system behaves, labelled "outside OLake docs". Amoro is the riskiest source because its
defaults differ from Fusion's. It is used for concepts only and labelled "upstream; Fusion may differ".

**Precedence when sources disagree:** the current OLake docs page, then GitHub release notes for anything newer (with
version and date), then READMEs, product FAQs and blog posts (dated), then vendor docs (only for that system, labelled),
then Amoro (concepts only, labelled), then issues (only as "known issue #N") ([olake-domain report][r-olake-domain]).

### 3.5 Citation URL policy

- **Docs `sources`**: the canonical sitemap URL. Use https, the apex host, a trailing slash, the original case (paths are
  case-sensitive, and one sitemap URL has capital letters), and no query or fragment. Canonical tags match the sitemap form
  on 267 of 267 pages. Slashless, http and www forms all 301 to it. Cite only URLs in the current sitemap. Never cite a legacy
  path: 305 of them return HTTP 200 with a meta-refresh rather than a 3xx. Never cite a stub. Dedupe and cap at 5
  ([docs-site report][r-docs-site]).
- **UI deep links**: add `#anchor` only if that id exists on the page. Ids follow github-slugger: 163/163 slugs matched,
  and 296/296 internal anchors resolve. 191 of 1,274 anchors (15%) sit inside hidden tabs. For those, use the site's own
  `?<param>=<value>#<id>` form, for example [Postgres CLI configuration][pg-tab]. 55 of 55 page-level tab labels map to
  their query values; tab groups inside shared partials need a second pass ([docs-site report][r-docs-site]).
- **Repo `sources`**: the `SOURCE_URL_STYLE` switch. The default `branch` gives
  `https://github.com/datazip-inc/<repo>/blob/master/<path>`. `sha` gives a full-SHA permalink with `#La-Lb`, or
  `?plain=1#La-Lb` for Markdown, which [GitHub requires for Markdown line links][gh-snippet]. The branch default is a guess
  at how graders match: it is the likelier string match, and it always shows current content. The [repos report][r-repos] argues for
  SHA links: they never change, and [GitHub documents][gh-perma] that branch links move. Kickoff question K3 decides.
  Either way, the UI card shows the SHA permalink labelled `repo@sha7 · path Lx-Ly`.
- **Releases** use `.../releases/tag/<tag>`. **Issues** use the issue or comment permalink. Never cite raw.githubusercontent.com.
- In `answer`, `[n]` markers are renumbered so that `[1]` is `sources[0]`.
- The POC scorer matches URLs leniently. It drops the scheme, fragment, query and trailing slash, and ignores the git ref
  (`poc/eval/questions.py`). The organizers' rule is unknown (K3).

### 3.6 Freshness

| Measurement | Value | Source |
|---|---|---|
| What `lastmod` means | It is the UTC date of the last commit to the page's own file (124/124 checked). 100 of the 124 dates come from one site-wide redesign commit on 2026-10-06, which touched 213 docs files. Edits inside shared partials never move it | [docs-site][r-docs-site] and [olake-domain][r-olake-domain] reports (git log on the olake-docs history) |
| Docs deploys | 6 successful deploys in about 26 h. Each takes 1m14s-2m40s, so commit-to-live is about 2 min. Every deploy changes `ETag` and `Last-Modified` on every page | [docs-site report][r-docs-site] (Actions runs API, header counts) |
| Docs churn | 25 commits touched `docs/` in the last 30 days and 44 in the last 60 | [olake-domain report][r-olake-domain] |
| Conditional GET | 304 in about 12 ms on a page and on the sitemap | `poc/results/freshness.json` |
| GitHub REST | Unauthenticated: 60 requests per hour, and each 304 still costs one. Authenticated: 5,000 per hour, and a 304 costs nothing | `poc/results/freshness.json`; [repos report][r-repos] |
| `git ls-remote` | 0.69-1.0 s per repo, no API quota | [repos report][r-repos]; `poc/results/freshness.json` |
| Compare API | v0.12.0...v0.12.1: 16 commits and 111 files, 14 of them on the allowlist | [repos report][r-repos] |
| Scheduling limits | Webhooks are impossible with pull-only access. [Scheduled Actions][gh-events] run at most every 5 minutes and can be delayed | [repos report][r-repos] |

**Decision.** Docs: poll `sitemap.xml` every 5-10 minutes with `If-None-Match`; a 304 means no deploy. On a 200, re-fetch
all 124 pages (about 2 MB and 2 s with gzip), hash the extracted text per page and per chunk, re-embed only the changed
chunks, and tombstone removed URLs. ETag, Last-Modified and `lastmod` are not content signals. Repos: `git ls-remote` HEAD;
on a new SHA, call the compare API, filter the changed files by the allowlist, fetch them at the new SHA, then re-chunk and
re-embed. Releases: the releases API. The manifest (build time, docs `lastmod` max, repo SHAs, latest tags) is shown in
`/healthz` and the UI footer. Version-sensitive answers say "Docs as of <date>; latest GitHub release <tag>". Re-crawl on
the morning of 2026-10-18. Open PRs could change correct answers around the event: streams v2 ([#1145][pr1145]), Azure
ADLS for Iceberg, and MySQL switchover CDC ([olake-domain report][r-olake-domain]). The in-app poller is decided (D9). PENDING(stack report:
whether the host keeps CPU for background work between requests).

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
  sizes are in §9. At a 600-token target, 556 of 951 chunks exceed the 512-WordPiece input limit of the bge embedders and get
  truncated. At 300 only 79 of 1,861 do (`poc/results/retrieval.json`), so 300 suits dense retrieval. PENDING(lead: confirm 300/450).
- **Retrieval.** BM25 (bm25s) and dense (fastembed) candidates fused with RRF, k=60 [[rrf]]. Then a cross-encoder
  rerank. Then small-to-big: the neighbouring chunk or parent section within about 4k context tokens, with at most 3 chunks
  per page. POC results on the 14 seed questions that have expected sources (`poc/results/retrieval.json`; 300-token chunks;
  fuse top 50, rerank top 20; latency is retrieval only, on an 18-core arm64 laptop with all ONNX threads):

  | Config | hit@1 | hit@5 | hit@10 | MRR@10 | p50 ms |
  |---|---|---|---|---|---|
  | BM25 | 0.286 | 0.714 | 0.857 | 0.451 | 0.24 |
  | Dense bge-small-en-v1.5 | 0.214 | 0.714 | 0.857 | 0.463 | 5.12 |
  | Dense bge-base-en-v1.5 | 0.357 | 0.786 | 0.929 | 0.567 | 12.16 |
  | Hybrid (RRF) bge-small | 0.357 | 0.714 | 0.929 | 0.511 | 5.79 |
  | Hybrid (RRF) bge-base | 0.429 | 0.786 | 0.857 | 0.581 | 13.53 |
  | Hybrid bge-base + rerank ms-marco-MiniLM-L-6-v2 | 0.429 | 0.786 | 0.929 | 0.590 | 431.29 |
  | Hybrid bge-base + rerank bge-reranker-base | 0.429 | 0.929 | 0.929 | 0.645 | 1786.92 |
  | BM25 + rerank ms-marco-MiniLM-L-6-v2 | 0.429 | 0.786 | 0.786 | 0.574 | 382.10 |

  With 14 questions, one question moves a hit rate by about 0.07, so differences of that size are noise. The best MRR
  (hybrid + bge-reranker-base) costs about 1.8 s per query on this machine. PENDING(lead: which embedder and reranker, and
  the rerank depth).
- **Grounding.** One system prompt (plan section 4.3): answer only from numbered passages, cite `[n]` per claim, and copy
  configs exactly. Fixed `NO_ANSWER` and `OUT_OF_SCOPE` markers. Prompt injection is treated as data.
- **Abstain.** Three triggers, each logged: (1) the top rerank score is below the threshold after one rewrite; (2) the
  model emits the don't-know marker; (3) no valid citation is left after parsing. **Targets**: abstain recall ≥ 90% on
  unanswerable plus out-of-scope rows, and false-abstain ≤ 5% on answerable rows. POC on the 18 seed questions
  (`poc/results/answer.json`; hybrid bge-base, MiniLM-L6 rerank, 6 passages, a local qwen3:32b): a gate on the top rerank
  score at -0.891 abstained on all 3 should-abstain questions and on none of the 14 should-answer ones (precision 1.0,
  recall 1.0). The model's own "answerable" flag added one false abstain (precision 0.75, false-abstain 0.071), on a
  false-premise question whose retrieval missed. The top MiniLM-L6 rerank score ranged 2.16 to 8.73 on answerable
  questions and -11.24 to -3.95 on the out-of-scope, unanswerable and adversarial ones (`poc/results/retrieval.json`).
  Too few rows to tune on. PENDING(re-tune on the curated set).
- **Honesty specifics** (decided): "not supported" or "not documented" with a fact-card citation is an answer, not an
  abstain. For pricing, SLA and enterprise questions, give no specifics and point to hello@olake.io or
  [the contact page][contact], as [/olake-go/][go-faq] does. Default credentials are stated only as the docs state them,
  with "change them for production". Issues are cited only as "known issue #N (open/closed; fixed in vX)".
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
`https://generativelanguage.googleapis.com/v1beta/openai/` (an API base URL, not a web page), and supports streaming. Its OpenAI-library support is
described as beta [[gemini-openai]]. PENDING(stack report: models, prices, rate limits, Gemma 4 availability).

### 5.2 Cost per answer
Measured in the POC with 6 passages of about 300 tokens each: a mean of 1,858 prompt tokens (max 2,169) and 71.8
completion tokens (max 145) per answer, counted by the local model's tokenizer (`poc/results/answer.json`). The memo's
estimate was about 4k input and 400 output. Cache hits cost 0. Cost per answer = tokens × the provider's price.
PENDING(stack report prices).

### 5.3 Embeddings and reranker
Local fastembed (ONNX on CPU), baked into the image. It does not depend on the provider, adds no marginal cost or rate limits,
is deterministic and works offline. API embeddings are the alternative if image size or host CPU becomes a problem.
Measured in the POC (`poc/results/retrieval.json`, `poc/results/latency_threads.json`). With 2 ONNX threads, a stand-in for a
2-vCPU host, measured on the laptop:

| Model | Dim | Query embed p50 (2 threads) | Rerank p50, top 10 / top 20 (2 threads) | Full-corpus embed (1,861 chunks, all cores) |
|---|---|---|---|---|
| BAAI/bge-small-en-v1.5 | 384 | 5.4 ms | | 69.09 s |
| BAAI/bge-base-en-v1.5 | 768 | 15.8 ms | | 229.79 s |
| Xenova/ms-marco-MiniLM-L-6-v2 (reranker) | | | 205.9 / 546.4 ms (358.2 ms for top 20 with passages cut to 1,000 chars) | |
| BAAI/bge-reranker-base (reranker) | | | 922.3 / 2,119.7 ms | |

Memory, as process RSS after loading each model in turn (2 threads): 245 MB after bge-small, 713 MB after MiniLM-L6, and
2,282 MB after bge-reranker-base (`poc/results/latency_threads.json`). So the larger reranker adds about 1.5 GB.
PENDING(stack report: image size and host CPU).

**Provisional choice (lead, pending the POC re-run on the canonical set):** 300-token chunks; the BAAI/bge-base-en-v1.5
embedder (dense MRR@10 0.567 vs 0.463 for bge-small, 15.8 ms per query at 2 threads); and the Xenova/ms-marco-MiniLM-L-6-v2
reranker on the top 10 (205.9 ms p50 at 2 threads). The MiniLM-L6 score also drives the abstain gate. The upgrade path is
BAAI/bge-reranker-base on the top 10 (922.3 ms p50 at 2 threads, RSS 2.3 GB; seed-set hit@5 0.929 vs 0.786). It is adopted
only if the 12:30 A/B (plan section 5, 2.5) confirms the gain and the host has at least 4 GB of RAM. `ABSTAIN_THRESHOLD` is
calibrated per reranker; the POC value for MiniLM-L6 is -0.891 (`poc/results/answer.json`).

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
The alternative is a Shadow DOM widget on the host page, which is what the POC built (`poc/api/static/widget.js`).

| | Loader plus iframe (chosen) | Shadow DOM widget (POC) |
|---|---|---|
| Style isolation | A separate document | Styles scoped to the shadow tree in both directions [[shadow-dom]] |
| What the host page's CSP must allow | `script-src` for `widget.js`, and our origin in `frame-src`, which falls back to `child-src` and then `default-src` [[frame-src]]. A plain iframe snippet needs only `frame-src` | `script-src` for `widget.js`, and our API origin in `connect-src`, because `fetch()` is governed by `connect-src`, which falls back to `default-src` [[connect-src]] |
| CORS | Not needed by the UI: the iframe calls its own origin | Needed: the host page calls our API from another origin |
| Access to the host page | None: messages only through `postMessage` | Runs in the host page's JavaScript context |

The POC ships a strict-CSP test page (`poc/api/demo/csp.html`, `connect-src 'self'`). There the Shadow DOM widget is
expected to render, but its API calls are expected to fail. PENDING(POC: the observed result).

### 5.7 Production basics
Pydantic validation (1-2000 characters), JSON errors, a 20 s LLM timeout with one jittered retry on 429/5xx, graceful
degradation, a concurrency semaphore that queues, a generous per-IP rate limit, CORS `*` without credentials, structured
JSON logs, `Server-Timing`, a non-root container user, and secrets only in env.

### 5.8 Latency and cost targets
**Targets** (unmeasured): `/ask` p50 ≤ 3 s and p95 ≤ 6 s with a Flash-class model; stream time to first token ≤ 1.2 s;
retrieval plus rerank ≤ 150 ms on 2 vCPU. Measured: no reranker meets the 150 ms **target** at 2 threads. MiniLM-L6 needs
205.9 ms p50 for the top 10 alone. Hybrid retrieval without a rerank takes 13.53 ms p50 on all cores, and its bge-base
query embedding alone takes 15.8 ms p50 at 2 threads (§4.3, §5.3). PENDING(POC end-to-end latency with the LLM).

## 6. Evaluation

Method: [eval-questions.md](eval-questions.md). The POC scorer (`poc/eval/score.py`) checks the response schema
(exactly `answer` and `sources`), the source hit with normalized URLs, behaviour by question type (abstain or decline
where expected), latency p50 and p95, and must-mention fact coverage judged by an LLM.

**Question sources.** Two research runs wrote grounded question sets on 2026-10-16, and the lead curates the final set
from them (PENDING(lead), [eval-questions.md](eval-questions.md)):
- [eval-ingestion report][r-eval-ingestion]: 40 questions (setup 7, sources 14, sync 11, destinations 8). 36 answerable and 4 negative, 20 easy /
  14 medium / 6 hard. 152 evidence quotes were checked against the fetched pages. 6 questions cite repo files, and 4 of
  those cannot be answered from the docs alone. A stdlib BM25 probe over 1,039 chunks put the best expected page at
  rank 1 for 31 of 40, in the top 3 for 36 and in the top 5 for 38.
- [eval-ops report][r-eval-ops]: 50 questions (catalogs 7, Fusion 8, deployment 7, troubleshooting 8, out-of-scope 6, unanswerable 6,
  false-premise 4, adversarial 4), 25 easy / 18 medium / 7 hard. 62 olake.io pages were fetched live, and 283 must-mention
  phrases were checked against their sources with none missing. For each unanswerable item, the answer was confirmed
  absent by searching the GitHub code, issues and releases and grepping the docs, blog and site source.

**POC results so far** (seed set, 18 questions, of which 14 have expected sources; small and noisy):
- Retrieval: the table in §4.3 (`poc/results/retrieval.json`).
- Answering (`poc/results/answer.json`, local qwen3:32b, so its latency says nothing about a hosted model): the answered
  questions hit an expected source 71.4% of the time. The abstain gate result is in §4.3. Retrieval took 13.7 ms p50 and the
  rerank 331.9 ms p50. On the local model's OpenAI-compatible API, only `reasoning_effort=none` turned thinking off: time to
  first token fell from 32,961 ms to 13,920 ms in the think probe. So set the hosted provider's lowest reasoning
  setting, and measure it at the 12:15 load test.
- PENDING: end-to-end accuracy with the event's model on the curated set, the threshold curve, latency and cost per answer
  with a hosted model.

## 7. Prior art and what judges probe

### 7.1 Prior art
PENDING(arch-prior-art report).

### 7.2 What the rubric lets judges probe

Derived from the rubric text ([challenges page][ch]). These are the checks we should expect, not reports of what these judges did.

| Criterion (weight) | Likely probe | Our evidence |
|---|---|---|
| Answer accuracy (35) | Setup, configuration and troubleshooting questions across both products, including Fusion | Eval table by category; config blocks copied verbatim from cited chunks |
| Citations and honesty (15) | Do the sources support the answer? Unanswerable, out-of-scope and false-premise questions | Gate 2 citation validation; abstain triggers logged; abstain recall and false-abstain rate measured (§6) |
| Production readiness (20) | Bad input, bursts of requests, a slow or failing LLM, prompt injection, health endpoints, logs | 422 with an error shape; a queue instead of rejection; timeout, retry and fallback provider; injection rules; `/healthz` and `/readyz`; JSON logs with request IDs |
| UX and easy embedding (15) | Embedding on a foreign page with one line, mobile, keyboard use, readable citations | The loader plus iframe on any origin; demo page; source cards; mobile full screen |
| Engineering (15) | Index age, latency, cost per answer | `/healthz` manifest and UI footer; p50 and p95; tokens and cost per answer in logs; exact-match cache |

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Credits throttle or stop during post-freeze scoring | Every row fails | A personal fallback trio (env only); a degraded mode that returns the most relevant pages; ask at kickoff (K1) |
| Endpoint down, cold or rate-limited while scoring | Production readiness and accuracy both lose | Min instances ≥ 1, a queue rather than rejection, a very high rate limit, a synthetic probe every minute (plan section 9) |
| The organizers match sources differently from us | Citation points lost | Canonical sitemap URLs and branch-form GitHub URLs; ask K3; matching in our own eval is lenient |
| Over-abstaining or under-abstaining | Accuracy or honesty points lost | Three logged triggers and a threshold tuned on the eval set (§4.3) |
| Venue Wi-Fi | Slow builds and deploys | Pre-cached wheels, models, repos and base image; remote builds; phone hotspot (plan section 11) |
| A teammate edits another track's files | Lost work | One owner per path (plan section 0.3) |
| Stale stub pages contradict live pages (e.g. "Kafka is WIP") | Confidently wrong answers | Denylist the stubs; fact cards with explicit negatives (§3.1, §3.3) |
| The docs lag the GitHub releases | Wrong "latest version" answers | A GitHub release-notes tier and the "Docs as of <date>; latest GitHub release <tag>" line (§3.6) |
| Upstream Amoro defaults differ from Fusion's | Confidently wrong Fusion answers | Do not index Amoro docs; use Amoro concepts only, labelled (§3.2, §3.4) |
| Default credentials sit in repo files | Leaked defaults or unsafe advice | Redact chunks; state only what the docs state, with "change them for production" (§3.2) |
| Pre-existing code | Disqualification. MLH's standard rules forbid re-using code or project materials and put all work inside the event ([MLH rules][mlh]) | Build fresh from the briefs; `poc/` is a reference for numbers only; disclose the preparation and the AI tools in the README (K6, D2) |

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
| Chunks over the bge 512-WordPiece limit | 79 of 1,861 (target 300); 556 of 951 (target 600) | `poc/results/retrieval.json` |
| Retrieval MRR@10 / hit@5, 300-token chunks, 14 seed questions | BM25 0.451 / 0.714; hybrid bge-base 0.581 / 0.786; + MiniLM-L6 rerank 0.590 / 0.786; + bge-reranker-base 0.645 / 0.929 | `poc/results/retrieval.json` |
| Retrieval p50 (all cores) | hybrid bge-base 13.53 ms; + MiniLM-L6 rerank 431.29 ms; + bge-reranker-base 1,786.92 ms | `poc/results/retrieval.json` |
| Rerank p50 at 2 threads, top 10 | MiniLM-L6 205.9 ms; bge-reranker-base 922.3 ms | `poc/results/latency_threads.json` |
| Query embedding p50 at 2 threads | bge-small 5.4 ms; bge-base 15.8 ms | `poc/results/latency_threads.json` |
| Full-corpus embedding (1,861 chunks) | bge-small 69.09 s; bge-base 229.79 s | `poc/results/retrieval.json` |
| Abstain gate on the top rerank score (18 seed questions) | threshold -0.891: precision 1.0, recall 1.0, false-abstain 0.0 (3 should abstain, 14 should answer) | `poc/results/answer.json` |
| Abstain on the model's own flag | precision 0.75, recall 1.0, false-abstain 0.071 | `poc/results/answer.json` |
| Answered questions that hit an expected source | 0.714 | `poc/results/answer.json` |
| Tokens per answer (6 passages) | prompt mean 1,858 (max 2,169); completion mean 71.8 (max 145) | `poc/results/answer.json` |
| Docs tokens from article text | 238,135 (o200k) | [docs-site report][r-docs-site], `measure_corpus.py` |
| Full docs fetch with gzip, 4 at a time | 2.07 MB in 2.2 s | [docs-site report][r-docs-site] |
| Pages whose content raw MDX misses | 22 of 124 | [docs-site report][r-docs-site], `hidden_content.py` |
| Anchors inside hidden tabs | 191 of 1,274 (15%) | [docs-site report][r-docs-site], `hidden_tab_headings.py` |
| Legacy paths answering 200 with a meta-refresh | 305 | [docs-site report][r-docs-site] (redirect config in `main.js`) |
| Docs deploys | 6 in about 26 h | [docs-site report][r-docs-site] (Actions runs API) |
| Docs release notes behind GitHub releases | 3-9 days (v0.8.0 to v0.12.0) | [olake-domain report][r-olake-domain] |
| BM25 hit@1/3/5 on 35 answerable seed questions | page level 18/26/29; chunk level 22/26/30; chunk level plus 3 rules 27/28/32 | [olake-domain report][r-olake-domain], `bm25_poc.py`, `bm25_rules.py` |
| Repo Tier A size | 377,136 bytes (about 94K tokens) | [repos report][r-repos] |
| spec.json converted to Markdown | 118,870 bytes to 39,612 bytes | [repos report][r-repos], `spec_to_md.py` |
| olake issues that are bot TODOs | 99 of 321 | [repos report][r-repos] |
| Grounded eval questions written | 40 (ingestion) + 50 (ops) | [eval-ingestion][r-eval-ingestion] and [eval-ops][r-eval-ops] reports |
| End-to-end accuracy, latency and cost with the event's model | PENDING | Curated eval set at the event |

## Sources

[ev]: https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake
[ch]: https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges
[r-docs-site]: reports/docs-site.md
[r-repos]: reports/repos.md
[r-olake-domain]: reports/olake-domain.md
[r-eval-ingestion]: reports/eval-ingestion.md
[r-eval-ops]: reports/eval-ops.md
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
[shadow-dom]: https://developer.mozilla.org/en-US/docs/Web/API/Web_components/Using_shadow_DOM
[frame-src]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-src
[connect-src]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/connect-src
[mlh]: https://github.com/MLH/mlh-policies/blob/main/standard-hackathon-rules.md
[rest]: https://olake.io/docs/writers/iceberg/catalog/rest/
[mdx-map]: https://raw.githubusercontent.com/datazip-inc/olake-docs/d06007140994ecbd239a52a9c0acf81fab4ed530/src/theme/MDXComponents/Index.js
[llms]: https://olake.io/llms.txt
[kafka]: https://olake.io/docs/connectors/kafka/
[go-aws]: https://olake.io/docs/install/olake-ui/offline-environments-aws/
[fus-aws]: https://olake.io/docs/fusion/install/olake-ui/offline-environments-aws/
[rel-0120]: https://olake.io/docs/release/ingestion/v0.12.0/
[rel-0100]: https://olake.io/docs/release/ingestion/v0.10.0/
[olake-rel]: https://github.com/datazip-inc/olake/releases
[fus-first]: https://olake.io/docs/fusion/getting-started/configure-first-compaction/
[fus-conf]: https://olake.io/docs/fusion/compaction/configuration/
[fus-faq]: https://olake.io/olake-fusion/
[go-faq]: https://olake.io/olake-go/
[mysql]: https://olake.io/docs/connectors/mysql/
[rootgo]: https://github.com/datazip-inc/olake/blob/d20c68ed98ced12293cd621ac04136a946ba4290/protocol/root.go
[values]: https://github.com/datazip-inc/olake-helm/blob/c63f10c48cd4dc2cbe3a130c6190ccedf0dafa83/helm/olake/values.yaml
[fus-claude]: https://github.com/datazip-inc/olake-fusion/blob/15ca160b298bf038f78f6639ec7aae67e4d4e33a/CLAUDE.md
[fus-notice]: https://github.com/datazip-inc/olake-fusion/blob/15ca160b298bf038f78f6639ec7aae67e4d4e33a/NOTICE
[amoro-conf]: https://amoro.apache.org/docs/latest/configurations/
[pg-tab]: https://olake.io/docs/connectors/postgres/?config-type=olake-cli#1-create-configuration-file
[gh-snippet]: https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-a-permanent-link-to-a-code-snippet
[gh-perma]: https://docs.github.com/en/repositories/working-with-files/using-files/getting-permanent-links-to-files
[gh-events]: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
[pr1145]: https://github.com/datazip-inc/olake/pull/1145
[contact]: https://olake.io/contact/
[mlh-guide]: https://guide.mlh.com/general-information/judging-and-submissions/rules-for-your-hackathon
[fusion-repo]: https://github.com/datazip-inc/olake-fusion
[amoro]: https://amoro.apache.org/

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
- MDN, Using shadow DOM: <https://developer.mozilla.org/en-US/docs/Web/API/Web_components/Using_shadow_DOM>
- MDN CSP `frame-src`: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-src>
- MDN CSP `connect-src`: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/connect-src>
- MLH standard hackathon rules: <https://github.com/MLH/mlh-policies/blob/main/standard-hackathon-rules.md>
- MLH organizer guide, rules for your hackathon: <https://guide.mlh.com/general-information/judging-and-submissions/rules-for-your-hackathon>
- olake-fusion repo: <https://github.com/datazip-inc/olake-fusion>
- Apache Amoro: <https://amoro.apache.org/>
- POC measurements: `poc/results/corpus.json`, `poc/results/chunks.json`, `poc/results/freshness.json`; POC code `poc/chunking/chunker.py`, `poc/eval/questions.py`, `poc/eval/score.py`
