# Ask OLake: research, comparisons and decisions

Status: final for 2026-10-17 (re-check the volatile items on the morning of 2026-10-18). Measured numbers name their
source file, and unmeasured goals are labelled **target**.
The runbook that carries out these decisions is [plan.md](plan.md). Open items are in [open-questions.md](open-questions.md).

## 1. Executive summary

1. **Deliverable**: a public `POST /ask` (`{"question"}` in, `{"answer", "sources"}` out), an embeddable chat UI, and a repo
   with a README on architecture and design choices ([challenges page][ch]).
2. **Corpus** (§3): tier 1 is the 124 `/docs/` pages from the rendered HTML minus a denylist of stub pages, plus GitHub
   release notes, the two product FAQs and fact cards generated at the event. Tier 2 is a Tier A repo allowlist and 10
   curated issues. Tier 3, the blog, is off (D4, decided by data: it lowered retrieval at full weight and was neutral at half weight). Tier 4 is about 23 curated outside pages,
   labelled. Not indexed: upstream Amoro docs (D11), bulk issues, discussions.
3. **Citations** (§3.5): `sources` holds canonical sitemap URLs (trailing slash, no anchor), capped at 5. For repo files,
   `SOURCE_URL_STYLE` switches between branch-form and SHA-permalink GitHub URLs (K3). Anchors and line ranges appear in
   the UI.
4. **Architecture**: hybrid retrieval (BM25 plus local dense embeddings, RRF k=60) with no cross-encoder in v1; FlashRank
   TinyBERT is a measured upgrade, switched on at 12:30 only if it helps on the event index (decision R′). The top 10
   chunks go to one grounded LLM call with `[n]` citations. An off-topic gate on the dense score short-circuits clearly
   off-topic questions, with no rewrite; its threshold is the lowest must-answer score minus a 0.02 margin. The model's
   `NO_ANSWER` and citation validation decide most abstains, and every abstain is logged. The fallback is BM25-only
   with the same chunks and prompt, behind a config flag (§4).
5. **Stack** (§5): Python 3.12 and FastAPI 0.135 or later (native SSE). The `openai` SDK drives an ordered chain of
   OpenAI-compatible providers: the event credits, then the operator's paid key of at least 100 RPM, then Gemma on the
   Gemini free tier. Retrieval uses fastembed bge-small (ONNX, CPU), bm25s and numpy vectors, with no reranker in v1. One
   container (2 GiB by default) runs on Cloud Run asia-south1 with one instance always on; DigitalOcean App Platform BLR is the fallback and an ngrok dev domain the emergency path. Latency, not cost,
   decides the model: answers cost $0.0004-0.0045.
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
| Docs size | 238,135 o200k tokens from article text ([docs-site report][r-docs-site], `measure_corpus.py`), or 264,265 from the POC's Markdown, which keeps code and table syntax (`poc/results/corpus.json`). 830 code blocks, 182 tables, 80 tab groups with 202 panels (122 hidden at load), 342 admonitions. The largest page is [the REST catalog page][rest] | [docs-site report][r-docs-site]; `poc/results/corpus.json` |
| Thin pages | 13 pages under 100 tokens (7 of them among the 23 Fusion pages), per the POC. The [docs-site report][r-docs-site] counts about 15 stub or stale pages, and the [olake-domain report][r-olake-domain] counts 18 pages under 1,300 characters | `poc/results/corpus.json`; both reports |
| Fetch cost | All 124 pages in 3.9 s (11.17 MB uncompressed), or 2.2 s and 2.07 MB with gzip, 4 at a time ([docs-site report][r-docs-site]). The POC took 7.52 s at concurrency 4 | [docs-site report][r-docs-site]; `poc/results/corpus.json` |
| Blog | 85 posts: 428,473 o200k tokens from article text ([docs-site report][r-docs-site]), or 446,275 from the POC's Markdown | [docs-site report][r-docs-site]; `poc/results/corpus.json` |

**Decision: rendered HTML, not raw MDX.** Raw MDX misses content on 22 of the 124 docs pages: every connector main page,
every catalog page, the Parquet writer pages, docker-cli and commands-and-flags. That content comes from 92 globally
registered MDX partials, 12 JSX config-table components, `FlagDetail.tsx` (CLI flags) and `DateTimeHandling.tsx`, all
registered in the site's [MDX component map][mdx-map]. For example, the Postgres `jsonb` to Iceberg `string` mapping exists
only in a partial and in the rendered HTML. The rendered HTML is complete: all 202 tab panels are server-rendered
([docs-site report][r-docs-site]). Extraction selectors: `.theme-doc-markdown` for docs and `#__blog-post-container` for posts.
Parse with lxml, never Python's `html.parser`. The minified production HTML omits optional end tags: on the REST catalog
page, 371 `<li` against 172 `</li>`, and 278 `<p` against 14 `</p>`. `html.parser` mis-nests that markup and concatenates
tab labels; lxml parses it correctly ([arch-prior-art report][r-arch]). The POC parses with lxml (`poc/ingest/html2md.py`).

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

The POC's retrieval and eval measurements (§4.3, §6) used a broader allowlist v1: 84 files, 143,596 tokens, with more Go
config structs (`poc/results/corpus.json` at POC commit 20b4bac). The POC's corpus v2 switched to the reports' Tier A list:
38 files, 80,176 tokens, with the connector `spec.json` files converted to Markdown field tables
(`poc/results/corpus.json`; `poc/ingest/repos.py`, `poc/ingest/spec2md.py`). It also indexes the last 10 GitHub releases
per repo: 34 notes, 8,602 tokens. The newest, olake v0.12.1, is newer than the docs' release notes, which stop at v0.12.0
(`poc/results/corpus.json`, `releases`; eval row REL-01). The event uses the Tier A list. Corpus v2 has not been
re-benchmarked; the retrieval numbers below are on corpus v1.

**[olake-fusion][fusion-repo] is a modified hard fork of [Apache Amoro][amoro].** The evidence: its [NOTICE][fus-notice] and DISCLAIMER; the
[root POM][fus-pom], whose own coordinates are `org.apache.amoro:amoro-parent:0.9-SNAPSHOT` and whose `<parent>` is
`org.apache:apache:23` (checked by the doc-writer at the pinned SHA); 119 files headed "Modified by Datazip"; and 1,851
imported upstream commits ([repos report][r-repos]). GitHub does not flag it as a fork. Its `docs/` and `site/` folders are upstream Amoro and are not
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
  path: the site's 285 redirect entries cover 305 legacy paths, which return HTTP 200 with a meta-refresh rather than a
  3xx (the [arch-prior-art report][r-arch] counts the same 285 entries). Never cite a stub. Dedupe and cap at 5
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
ADLS for Iceberg, and MySQL switchover CDC ([olake-domain report][r-olake-domain]). The in-app poller is decided (D9). On Cloud Run, CPU is throttled outside requests unless the service is deployed
with `--no-cpu-throttling` [[gcloud-deploy]], so use that flag whenever the poller runs (§5.5).

## 4. Architecture

### 4.1 Options

| | A. Simple | B. Hybrid + gates, no rerank in v1 (chosen; measured) | C. Agentic tool loop | D. Long-context stuffing |
|---|---|---|---|---|
| Retrieval | BM25 over heading-aware chunks, top 10 | BM25 + local dense, RRF k=60 [[rrf]]; the top 10 chunks (max 3 per page) go to the LLM; no cross-encoder in v1, with TinyBERT as a conditional upgrade (§4.3) | Tools (`search_docs`, `search_repo`, `open_page`) chosen by the LLM | None: the whole docs set goes in the prompt |
| LLM calls per answer | 1 | 1 (0 when the off-topic gate short-circuits) | Several | 1, very large |
| Build effort | About 1 hour (memo estimate, unmeasured) | The 10:30-13:30 build window (plan section 3) | Not planned for v1 (memo) | Small, but rejected for serving |

### 4.2 Options against the judging criteria

Qualitative: the lead's design memo plus the doc-writer's reading of the options. These are judgments, except where §4.3
gives a measured number. The prior art and literature follow the table.

| Criterion (weight) | A. Simple | B. Chosen | C. Agentic | D. Long context |
|---|---|---|---|---|
| Answer accuracy (35) | Weak on paraphrased questions (lexical match only); canonical MRR@10 0.68 | Hybrid recall: canonical MRR@10 0.736, hit@10 0.939 (§4.3) | Better on hard multi-hop questions | No retrieval misses, but the whole corpus is in every prompt |
| Citations and honesty (15) | `[n]` mapping; abstain only from the model | Three abstain triggers, citation validation | More steps between a citation and the retrieved text | Citations must name pages inside one huge context |
| Production readiness (20) | Few moving parts | More parts, but each one is local and deterministic | More failure modes (loops, tool errors) | Depends on a ~1M-token-context provider |
| UX and embedding (15) | Same widget | Same widget; streaming | Slower first token | Slowest |
| Engineering: latency and cost (15) | Cheapest | One LLM call; local retrieval has no marginal cost | 2-4x latency and cost (memo estimate, unmeasured) | Highest cost per answer |
| Engineering: freshness | Rebuild chunks | Rebuild chunks and vectors incrementally | Same as B | Re-send everything each call |

**Prior art and literature** (from the [arch-prior-art report][r-arch], which links each source):
- **The research agent's scoring.** This is its judgment, not a measurement. Each design scored 1-5 per criterion, with
  the rubric's weights 35/15/20/15/15; the total is the sum of score × weight / 5.

  | Design (the report's name) | Accuracy (35) | Citations and honesty (15) | Production (20) | UX and embed (15) | Engineering (15) | Total |
  |---|---|---|---|---|---|---|
  | "Recommended", close to our B: A plus a sufficiency gate, citation verification, streaming, cache, freshness and hardening | 4 | 5 | 4 | 5 | 4 | 86 |
  | "Ambitious", close to our C: agentic with CRAG, several sources, a hosted reranker, a Self-Route long-context fallback and claim-level NLI | 4 | 3 | 3 | 4 | 2 | 67 (range about 62-77) |
  | "Simple fallback", close to our A: crawl, breadcrumb chunks, hybrid RRF, one LLM call with `[n]` citations, FastAPI, a basic widget | 3 | 3 | 4 | 3 | 4 | 67 |

  The report also says to build A first as the safety net, then add B's features in rubric-weight order.
- **Hybrid with RRF.** In Cormack et al.'s pilot, k=60 was near-optimal but "not critical", and RRF beat the best single
  system by 4-5% on average [[rrf]]. BEIR found BM25 a robust zero-shot baseline that dense retrievers often fail to beat
  [[lit-beir]]. In Bruch et al.'s tests, a tuned convex combination of normalized scores beat RRF, but it needs labelled
  queries to tune its weight [[lit-bruch]]. RRF needs no tuning data: the standard k=60, which the POC measured on the
  curated set (§4.3), is the right choice for a 3-hour build.
- **Chunk headers.** Anthropic's Contextual Retrieval cut the top-20 retrieval failure rate from 5.7% to 3.7% with
  contextual embeddings, to 2.9% when contextual BM25 was added, and to 1.9% with a Cohere rerank on top
  [[lit-contextual]]. In dsRAG's KITE benchmark (LLM-graded, 0-10), contextual chunk headers raised the score from 4.72 to
  6.04 [[lit-dsrag]]. On OLake, the report's
  probe measured +11 to +14 points of Hit@1 from a breadcrumb prefix (44 questions). Every I1 chunk header carries that
  breadcrumb.
- **Rerankers.** The published gains come from hosted rerankers (the Anthropic numbers above, and
  [Ask Astro][pa-ask-astro-blog]). On OLake, small open cross-encoders lowered Hit@1 in the report's probe (hybrid with
  breadcrumbs 0.864; + MiniLM-L6 0.773; + jina-reranker-v1-turbo 0.750; 44 questions). In the POC on the 94-row set the
  heavier cross-encoders did not help, while the tiny TinyBERT@20 raised MRR@10 from 0.744 to 0.778 on corpus v2 and is a
  conditional upgrade (§4.3). A hosted reranker is untested on OLake.
- **Long context (D).** Li et al. (2024) found that long context beats RAG on average (Gemini-1.5-Pro 49.70 vs 37.33;
  GPT-4o 48.67 vs 32.60). Their Self-Route (RAG first, long context only when the model says it cannot answer) comes
  close while using 38-61% of the long-context tokens [[lit-selfroute]]. Accuracy drops when the relevant passage sits in
  the middle of a long context [[lit-litm]]. Anthropic suggests putting the whole knowledge base in the prompt below about
  200k tokens [[lit-contextual]]. The docs are above that: about 270k tokens by the report's estimate, and 264,265 o200k
  tokens in the POC (§3). Hence D is rejected for serving.
- **Corrective and agentic loops (C).** CRAG adds a retrieval evaluator and a web-search branch. On PopQA its
  generation-only time per question was 0.512 s, against 0.363 s for plain RAG [[lit-crag]].

Decision: **B, hybrid RRF without a cross-encoder in v1 (measured)**, with TinyBERT as a conditional upgrade (§4.3) and
**A** always available as the fallback: same chunks, same prompt, switched by `RETRIEVAL_MODE`.
C is a possible low-confidence escalation only if time allows. D is rejected for serving and kept as a debugging oracle.

### 4.3 Pipeline details

- **Chunking.** Split at headings and tab markers. Never split inside a code fence or table. Every chunk gets a
  `title › section` header. YAML and JSON split at keys, and Go at top-level declarations (`poc/chunking/chunker.py`). Measured
  sizes are in §9. At a 600-token target, 556 of 951 chunks exceed the 512-WordPiece input limit of the bge embedders and get
  truncated. At 300 only 79 of 1,861 do (corpus v1, `poc/results/retrieval.json`). On the canonical set, every config scores lower at
  600 than at 300; for example, hybrid bge-small falls to MRR@10 0.719 from 0.736 (`poc/results/retrieval-canonical.json`).
  **Decision: a 300-token target with a 450 hard max** (the POC chunker's 300 configuration). The 600-token option is dropped.
  The context header is backed by evidence: in the arch report's probe, a breadcrumb prefix raised Hit@1 by 11-14 points
  (44 questions), in line with Anthropic's Contextual Retrieval and dsRAG (§4.2).
  Considered and not adopted: the arch report suggests a 400-500-token soft cap and the fused top 8. Ours is measured on
  the 82-row canonical set: 300 beats 600 on every config, and hit@10 is 0.939 (`poc/results/retrieval-canonical.json`).
  The report's suggestion comes from a 44-question set with one annotator.
- **Retrieval.** BM25 (bm25s) and dense (fastembed) candidates fused with RRF, k=60 [[rrf]], with **no reranker**
  (decided on the numbers below; TinyBERT over the fused top 20 is a conditional upgrade, decision R′). RRF needs no
  tuning data, unlike a tuned score blend (§4.2). The top 10 fused chunks, at most 3 per page, go to the LLM: about 3.3k prompt
  tokens, measured at 3,294 on average (p50 3,253, max 4,545) with k=10 and prompt v3 (`poc/results/eval_run-canonical-combined.json`).
  First, the POC results on the 14 seed questions with expected sources (`poc/results/retrieval.json`; 300-token chunks;
  fuse top 50, rerank top 20; retrieval latency only, on an 18-core arm64 laptop with all ONNX threads):

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
  (hybrid + bge-reranker-base) costs about 1.8 s per query on this machine.

  **Canonical set**: the 82 rows of the curated set that have expected sources, at 300-token chunks
  (`poc/results/retrieval-canonical.json`; the bge-reranker-base row comes from
  `poc/results/retrieval-canonical-bge-reranker.json`, which is a transcription of the run's log, not a JSON the bench wrote):

  | Config | MRR@10 | hit@5 |
  |---|---|---|
  | BM25 | 0.680 | 0.854 |
  | Dense bge-small-en-v1.5 | 0.692 | 0.854 |
  | Dense bge-base-en-v1.5 | 0.702 | 0.829 |
  | Hybrid (RRF) bge-small | 0.736 | 0.866 |
  | Hybrid (RRF) bge-base | 0.745 | 0.890 |
  | Hybrid bge-small + rerank MiniLM-L6 | 0.746 | 0.829 |
  | Hybrid bge-base + rerank MiniLM-L6 | 0.734 | 0.854 |
  | BM25 + rerank MiniLM-L6 | 0.742 | 0.829 |
  | Hybrid bge-small + rerank bge-reranker-base (log transcription) | 0.664 | 0.829 |

  The other ranks, from the same files (hit@1 / hit@3 / hit@10):
  - Hybrid (RRF) bge-small, the chosen config: 0.634 / 0.829 / 0.939.
  - Hybrid (RRF) bge-base: 0.646 / 0.817 / 0.927.
  - Hybrid bge-small + MiniLM-L6: 0.671 / 0.780 / 0.939.
  - BM25: 0.549 / 0.793 / 0.915.
  - Hybrid bge-small + bge-reranker-base (log transcription): 0.549 / 0.744 / 0.890.

  Findings:
  - Hybrid clearly beats either retriever alone.
  - bge-small comes close to bge-base, and it embeds the corpus 3.3x faster (69.09 s vs 229.79 s,
    `poc/results/retrieval.json`).
  - The MiniLM-L6 rerank leaves MRR flat (0.746 vs 0.736) and makes hit@3 and hit@5 worse (0.780 vs 0.829, 0.829 vs 0.866).
  - bge-reranker-base makes MRR worse (0.664, log transcription).
  - At 600-token chunks every config scores lower.
  - Identifier questions (CLI flags, and config keys defined only in Go) are where dense retrieval fails and BM25 rescues
    them. An exact-match boost for `--flags` and `snake_case` keys found in the question is a cheap next step
    (`poc/README.md`, finding 7). The plan adds it to the BM25 query.

  **Decision: no reranker in the ranking path.** A reranker is only an optional patch-hour experiment. Independent
  corroboration: in the arch report's probe (44 questions), small open cross-encoders also lowered Hit@1, from 0.864 for
  hybrid with breadcrumbs to 0.773 with MiniLM-L6 and 0.750 with jina-reranker-v1-turbo ([arch-prior-art report][r-arch]). The context gets the
  top 10 chunks, not 6, because hit@10 is 0.939. With 6 passages (hybrid bge-base plus MiniLM-L6), an expected source was in
  the context for 70 of the 82 rows with expected sources (85.4%, `poc/results/gate-canonical.json`,
  `context_hit_rate_top_passages`).

  **Corpus v2, decision R′ and decision D4** (`poc/results/retrieval-v2.json`: corpus v2, 300-token chunks, hybrid
  bge-small, the 82 rows with expected sources; rerank latency on an 18-core laptop with all ONNX threads):

  | Config | MRR@10 | hit@1 | hit@3 | hit@5 | hit@10 | Rerank p50 ms |
  |---|---|---|---|---|---|---|
  | No rerank | 0.744 | 0.634 | 0.854 | 0.878 | 0.939 | |
  | + FlashRank TinyBERT, top 10 | 0.749 | 0.634 | 0.829 | 0.890 | 0.939 | 13.96 |
  | + FlashRank TinyBERT, top 20 | 0.778 | 0.683 | 0.841 | 0.902 | 0.939 | 28.14 |
  | + MiniLM-L6, top 10 | 0.731 | 0.634 | 0.768 | 0.866 | 0.939 | 150.82 |
  | + MiniLM-L6, top 20 | 0.742 | 0.646 | 0.793 | 0.841 | 0.939 | 339.68 |
  | + bge-reranker-base, top 10 | 0.682 | 0.549 | 0.780 | 0.866 | 0.939 | 911.00 |
  | + bge-reranker-base, top 20 | 0.649 | 0.500 | 0.768 | 0.866 | 0.915 | 1,646.25 |
  | Blog tier added, rank weight 1.0 | 0.630 | 0.524 | 0.707 | 0.805 | 0.866 | |
  | Blog tier added, rank weight 0.5 | 0.743 | 0.634 | 0.841 | 0.890 | 0.939 | |

  **Decision R′ (the lead's call): v1 ships without a cross-encoder**, which keeps the 10:30-12:00 build simple. TinyBERT
  over the top 20 is the first measured upgrade: MRR@10 0.778 vs 0.744, at 28 ms with a 4 MB model. The LLM gets the top
  10 either way and hit@10 is unchanged, so the gain is ordering only: 4 more rows with an expected source at rank 1 (56
  vs 52 of 82), from a single run. Checkpoint 2.7 switches `RERANK=tinybert` on only if the retrieval-only bench on the
  event index shows at least +0.02 MRR@10 and no hit@10 loss. MiniLM-L6 and bge-reranker-base stay rejected. Why TinyBERT
  helps when the larger cross-encoders do not is unexplained. One hypothesis, untested: it mostly scores the breadcrumb
  header and the first lines of each chunk. FlashRank truncates the query and passage to `max_length`, which the POC set to
  512 (`poc/retrieval/index.py`), so truncation alone would clip only the longest chunks.

  **By category** (same file, `by_category`; MRR@10 / hit@10):

  | Category (rows) | No rerank | + TinyBERT, top 20 |
  |---|---|---|
  | catalogs (9) | 0.826 / 1.000 | 1.000 / 1.000 |
  | deployment (10) | 0.850 / 0.900 | 0.850 / 0.900 |
  | destinations (8) | 0.828 / 1.000 | 0.688 / 0.875 |
  | freshness (1) | 0.500 / 1.000 | 0.333 / 1.000 |
  | setup (8) | 0.750 / 1.000 | 0.812 / 1.000 |
  | source-config (18) | 0.738 / 0.944 | 0.789 / 0.889 |
  | sync-modes (13) | 0.674 / 0.846 | 0.598 / 0.923 |
  | table-maintenance (9) | 0.701 / 1.000 | 0.752 / 1.000 |
  | troubleshooting (6) | 0.597 / 0.833 | 0.875 / 1.000 |

  - Without a reranker, troubleshooting (0.597) and sync-modes (0.674) are the weakest categories.
  - TinyBERT's gain is concentrated in troubleshooting and catalogs. It lowers destinations and sync-modes MRR, and
    behind the unchanged overall hit@10, two rows leave the top 10 (SRC-09 from rank 2, DST-06 from rank 8) while two
    enter (SYNC-12 at rank 5, TRB-02 at rank 1). 11 rows gain rank 1 and 7 lose it (`first_hit_rank`). This honest
    single-run trade-off is why the upgrade is conditional. Checkpoint 2.7 keeps the aggregate rule (MRR@10 up by at least
    0.02, aggregate hit@10 not lower) on purpose: any reranker swaps some rows across the top-10 boundary, and what matters
    for answers is the net number of rows whose expected source reaches the 10-passage context. A guard line prefers
    `RERANK=off` if a row that leaves the top 10 is in a category already weak at hit@10 (sync-modes, troubleshooting).
  - Fusion is covered: all 8 FUS rows have an expected source in the top 10, 7 of them at rank 1 or 2 (FUS-04 at 9).
  - Corpus v2 against v1 (`first_hit_rank` in `poc/results/retrieval-canonical.json` and `poc/results/retrieval-v2.json`):
    REL-01 moves from rank 8 to 2, because the GitHub release notes are now indexed, and FUS-07 from rank 5 to 1.

  **Decision D4, by data: the blog is off.** At full weight the blog chunks dropped MRR@10 to 0.630; at a 0.5 rank weight
  they were neutral (0.743 vs 0.744). With no upside on the eval set and a staleness risk, `BLOG=off`. The blog stays a
  documented opt-in at the 0.5 penalty, for conceptual "why Iceberg" questions only.
- **Grounding.** One system prompt (plan section 4.3): answer only from numbered passages, cite `[n]` per claim, and copy
  configs exactly. Fixed `NO_ANSWER` and `OUT_OF_SCOPE` markers. Prompt injection is treated as data.
- **Abstain: the reranker score cannot decide it.** On the 18 seed questions, a gate on the top MiniLM-L6 rerank score at
  -0.891 looked perfect (precision and recall 1.0; `poc/results/answer.json`). That did not hold on the 94-row curated set
  (`poc/results/gate-canonical.json`: 12 rows should abstain, the 6 unanswerable and 6 out-of-scope; 82 should answer):
  - At -0.891 the gate caught only 6 of the 12 (recall 0.5) and false-abstained on 3 of 69 answerable rows (4.3%). The
    doc-writer recomputed this from `per_question` in that file.
  - The best single threshold, 1.18, reached recall 0.917, but with precision 0.44, false abstains on 13% of answerable
    rows and 17.1% of all must-answer rows.
  - The score ranges overlap. A near-domain unknown scores high (UNK-01: 6.28), and an injection-wrapped real question
    scores very low (ADV-03: -6.36). Answerable rows range from -2.67 to 7.78.
- **Abstain policy** (decided by the lead after this result):
  1. The gate is only a cheap off-topic short-circuit. **The signal is the highest dense cosine**
     (`GATE_SIGNAL=dense`), measured on the POC's corpus v2 (bge-small, 300-token chunks; `poc/results/gate-signals.json`).
     At 0 false abstains on the 82 must-answer rows, it caught 7 of the 12 must-abstain rows (recall 0.583, threshold
     0.7126), against 0.417 for TinyBERT over the top 10, 0.333 for MiniLM-L6 and 0 for BM25. It needs no extra model and
     adds no latency, because retrieval already embeds the query. The rows it cannot catch are near-domain: UNK-02 (0.823),
     UNK-01 (0.800), OOS-03 (0.779), UNK-05 (0.774) and UNK-03 (0.728). The arch report's probe agrees (bge-small; 44
     answerable, 14 on-topic unanswerable and 6 off-topic questions). The top-1 dense cosine separated off-topic
     questions perfectly (AUROC 1.0; off-topic 0.512-0.608, answerable 0.732-0.924), but on-topic unanswerables only
     partly (AUROC 0.886; normalized BM25 0.409). At 95% answer coverage it refused 100% of off-topic questions and 36%
     of unanswerables ([arch-prior-art report][r-arch]). So the gate handles off-topic questions only, and the model's
     sufficient-context judgment does the rest, backed by citation validation, because models hallucinate on 15-40% of
     insufficient-context questions [[lit-suffctx]].
     **Threshold: the lowest must-answer dense score minus a 0.02 margin**, calibrated at checkpoint 2.5 on the event index
     (plan section 5). Every 0-false-abstain threshold has zero margin, because the lowest must-answer row sits right at it
     (SYNC-11 0.7126, FP-03 0.7127). The starting value is 0.69. There the gate alone caught 5 of the 12 must-abstain rows
     (0.417) with 0 false declines; the margin gives up OOS-05 (0.699) and UNK-04 (0.701) (`poc/results/gate-rewrite.json`,
     `poc/results/gate-signals.json`).
  2. **No rewrite step by default (measured).** With the dense gate, one LLM rewrite before the short-circuit adds nothing
     (`poc/results/gate-rewrite.json`, written by `poc/answer/rewrite_probe.py`). At 0.71 the gate alone reached recall
     0.583 with 0 false declines; gate plus one rewrite reached 0.500, because the rewrite "rescued" UNK-04 (0.701 to
     0.715), which should be declined. Every must-answer row, the injection-wrapped ones included, already scores at or
     above 0.7126, so nothing needs rescuing. The rewrite call is also injectable: for ADV-01 it emitted the injected claim, and
     for ADV-02 a refusal sentence. Only retrieval sees that output, but it is an attack surface, and it costs about 1.2 s
     locally (p50 1,174.8 ms; 191.7 prompt and 11.9 completion tokens on average). So the rewrite is optional, only with a
     TinyBERT gate. If it is ever used, its prompt emits keywords only (no sentences, about 12 tokens at most), and its
     output is never shown to the user. A hardened rewrite prompt of that kind, with an output sanitizer, was no net gain
     on the 14 gate-fired and adversarial rows: ADV-01 then produced keywords, but ADV-02 was still declined, and UNK-06
     and OOS-05 passed the gate (`poc/results/gate-rewrite-v2-subset.json`). A short-circuit returns one unified text, which also suits the near-domain
     unknowns the gate catches, such as UNK-06 (SOC 2), whose BEHAVIOR item needs the contact pointer:
     "I couldn't find this in the OLake docs or repos. I can help with OLake setup, sources, sync modes, catalogs, Fusion
     maintenance, deployment and troubleshooting. If your question is about OLake, ask in the OLake Slack or GitHub
     Discussions; for commercial or security questions, contact hello@olake.io."
  3. The real abstain decision comes from the model (the `NO_ANSWER` marker or "answerable" flag) plus citation validation.
     With no valid citation left, it abstains. This is decision D8, decided by data: in the canonical run the rule caused 0
     of the 13 false abstains on must-answer rows (§6).
  4. Negative and false-premise answers say "not supported", or correct the premise, with the citation of the page that
     lists what is supported. They never say "the docs don't mention X". The scorer skips abstain matching on those rows.

  Every abstain is logged with its reason. **Targets**: abstain recall ≥ 90% on unanswerable plus out-of-scope rows, and
  false-abstain ≤ 5% on answerable rows.

  **Measured end to end, and both abstain targets were MISSED.** The POC API ran with the v1 prompt and a local qwen3:32b,
  on all 94 rows (`poc/results/eval_run-canonical.json`):
  - abstain recall 0.833, against the ≥ 0.90 target;
  - false-abstain 0.072 on answerable rows, against the ≤ 0.05 target.

  In the round-2 proxy run (§6: prompt v3, k=10, a TinyBERT gate with one rewrite), false-abstain on answerable rows fell
  to 0.043, which **meets** the target, while abstain recall stayed at 0.833, which still **misses** it. The judge passed
  all 6 unanswerable rows' BEHAVIOR items, though: the two "missed" ones say what is not documented, with sources.

  Treat these as lower bounds from a local 32B model. The event-day levers:
  - a stronger hosted model;
  - the "unsupported or undocumented" fact card for near-domain unknowns;
  - the unified short-circuit text above;
  - the v2 prompt, which corrects false premises and answers the real question inside injection attempts (the POC made it
    selectable by env var in POC commit 300e9c2);
  - three prompt rules from the canonical run's wrong abstains (§6): answer negatives from the list of what is supported
    even when no passage names the feature (SRC-08); call a "coming soon" feature not available or documented yet, with no
    date (UNK-04); decline another tool's configuration (OOS-03);
  - for type-mapping misses (SYNC-12, Postgres jsonb): keep tables whole in chunks, plus the exact-match boost for
    identifiers;
  - plain-text generation with no JSON mode, plus one retry and then salvage on unparseable or truncated output: 2 of the
    4 false abstains in the round-2 run were JSON-parse failures (§6);
  - two untested patch-hour ideas (§6): strip injection-like sentences before retrieval, and a per-claim support check.

  The closest end-to-end measurement is the round-2 run (§6): a close proxy of the recommended model stage, with a
  different gate; §6 lists the differences. The final policy itself is measured at checkpoints 2.2 and 2.5 on the day: the full eval against the
  deployed URL, with each row's abstain reason read from the X-Ask-Reason header. The gate's offline effect is measured
  above. On the seed set, the model's own flag added one false abstain
  (precision 0.75, false-abstain 0.071), on a false-premise question whose retrieval missed (`poc/results/answer.json`).
- **Honesty specifics** (decided): "not supported" or "not documented" with a fact-card citation is an answer, not an
  abstain. For pricing, SLA and enterprise questions, give no specifics and point to hello@olake.io or
  [the contact page][contact], as [/olake-go/][go-faq] does. Default credentials are stated only as the docs state them,
  with "change them for production". Issues are cited only as "known issue #N (open/closed; fixed in vX)".
- **Caching.** An exact-match LRU keyed on the normalized question plus the index version. No semantic cache, because a
  near-duplicate question can need a different answer. A stable system-prompt prefix lets providers cache the prompt.
- **Streaming.** `POST /ask/stream` sends SSE (`meta`, `token`, `done`, `error`) for the UI only. The browser reads it with
  `fetch()` because `EventSource` cannot POST [[mdn-es]].

## 5. Stack

Sources: the [stack report][r-stack] (2026-10-16; methods and raw numbers are in it), the lead's stack decisions, and the
POC result files named below.

### 5.1 Credits: what the event actually offers
- The event provides "LLM API credits" without naming a provider ([event page][ev]).
- **Gemma 4 on the Gemini API.** The MLH Gemma links lead here. Only `gemma-4-31b-it` and `gemma-4-26b-a4b-it` are
  served, and only on the free tier: the paid tier is listed as "Not available", and free-tier data is used to improve
  Google's products ([Gemini pricing][gem-pricing]). Rate limits are shown only in AI Studio ([rate limits][gem-rl]); a
  [third-party snapshot][tilnote] reports about 15 RPM and 1,500 requests per day for Gemma 4. The Gemini OpenAI-compatible
  endpoint is not documented for Gemma ([OpenAI compatibility][gemini-openai]), so verify it on the day.
- **DigitalOcean.** The MLH DigitalOcean link ([mlh.link/digitalocean][mlh-do]) promises $200, but its signup link returned
  a 302 to the DigitalOcean homepage when tested, and DigitalOcean's docs describe only a $5 signup credit
  ([stack report][r-stack]). DigitalOcean serverless inference is OpenAI-compatible: the API base is
  `https://inference.do-ai.run/v1`, Tier 1 gets 120 RPM and 1.5M TPM, and it is prepaid only ([limits][do-limits],
  [pricing][do-pricing]).
- **Free tiers will throttle a scorer burst.** Groq's free plan allows 8K TPM, about 2 requests per minute at 4k tokens
  ([Groq rate limits][groq-rl]). A Cerebras trial allows 5 RPM, and Gemma on the Gemini free tier about 15 RPM
  ([stack report][r-stack]).
- **Decision.** Use an ordered fallback chain of (base URL, model, key), behind a global semaphore with a bounded wait
  (§5.7). The order is
  always:
  1. the event credits;
  2. the operator's paid personal key with at least 100 RPM: OpenAI gpt-6-luna, a Groq developer key, or a prepaid
     DigitalOcean balance (decision D7);
  3. Gemma on the Gemini free tier, last: about 15 RPM, the data is used by Google, and the OpenAI-compatible path is
     unverified.

  Kickoff question K1 decides which models to try on the credits (decision D3).

### 5.2 Generator candidates and cost
Latency decides, not cost. At 4k input and 400 output tokens, an answer costs between $0.0004 and $0.0045 depending on
the model. Time to first token ranges from 0.4 s to 24 s depending on the reasoning settings ([stack report][r-stack],
using [Artificial Analysis][aa] medians). The POC's real answers averaged 1,858 input and 71.8 output tokens
(`poc/results/answer.json`), so the actual cost is lower still.

| Candidate | API base | $ per 1M in / out | TTFT and speed (Artificial Analysis) | Note |
|---|---|---|---|---|
| gemini-3.8-flash, reasoning_effort low | `generativelanguage.googleapis.com/v1beta/openai/` | 0.75 / 3.75 (doubles 2027-01-01) | 23.6 s at high reasoning; low and minimal must be measured | Best Flash-class quality (index 40.9). Gemini 3 reasoning cannot be turned off |
| gemini-3.5-flash-lite, minimal | same | 0.30 / 2.50 | 6.98 s, 446 tok/s (default settings) | |
| gemini-3-flash-preview | same | 0.50 / 3.00 | 0.94 s, 200 tok/s | Preview model |
| DO openai-gpt-oss-120b | `inference.do-ai.run/v1` | 0.10 / 0.70 | provider-dependent | DO credits, 120 RPM |
| DO gemma-4-31B-it | same | 0.18 / 0.50 | about 2 s, 44-48 tok/s | Open-weight (Gemma prize angle) |
| Groq openai/gpt-oss-120b (paid developer plan) | `api.groq.com/openai/v1` | 0.15 / 0.60 | 0.71 s, 474 tok/s | Fastest TTFT; the free plan is too small |
| OpenAI gpt-6-luna (non-reasoning) | `api.openai.com/v1` | 0.10 / 0.50 | 0.94 s, 117 tok/s | Needs the operator's own key |
| claude-haiku-5-5 (low) | `api.anthropic.com/v1/` (compatibility layer) | 0.10 / 0.50 | 6.85 s | The layer ignores `response_format` |
| gemma-4-26b-a4b-it, Gemini free tier | Gemini OpenAI-compatible (unverified) | 0 | 0.97 s, 46.8 tok/s | Last resort: about 15 RPM, and the data is used for training |

Sources: the [stack report][r-stack] (prices from the providers' pricing pages, for example [Gemini][gem-pricing] and
[DigitalOcean][do-pricing]; speeds parsed from [Artificial Analysis][aa]). Cost per answer at 4k in and 400 out: GPT-6 Luna
$0.00060, Claude Haiku 5.5 $0.00060, Groq gpt-oss-120b $0.00084, DO Gemma 4 31B $0.00092, Gemini 3.5 Flash-Lite $0.00220,
Gemini 3.8 Flash $0.00450, Gemma on the Gemini free tier $0 ([stack report][r-stack], `cost.py`).

**Client rules** (decided):
- Use the `openai` SDK (a 2.2 MB wheel, against 38.8 MB for LiteLLM) with `timeout` about 25 s and `max_retries` 1. The
  SDK's defaults are a 10-minute timeout and 2 retries ([SDK README][openai-readme]). Always pass `max_tokens` (1500; §5.7).
- Fail over to the next provider before the first streamed byte.
- Never depend on `response_format`; parse defensively. Anthropic's compatibility layer ignores it
  ([Anthropic OpenAI SDK compatibility][claude-compat]), DigitalOcean does not document it
  ([serverless inference API][do-inference-api]), and it is unverified for Gemma.
- Set `reasoning_effort` to the lowest value the model supports. Gemini 3 thinking cannot be switched off
  ([OpenAI compatibility][gemini-openai]). On the POC's local model, only `none` switched thinking off
  (`poc/results/answer.json`, think probe).

The model is chosen on the day by measurement (decision D3).

### 5.3 Embeddings and reranker
Local fastembed models (ONNX on CPU) are baked into the image. They work with any LLM provider, cost nothing per query,
have no rate limit and work offline. Measured in the POC (`poc/results/retrieval.json`, `poc/results/latency_threads.json`;
2 ONNX threads as a stand-in for a 2-vCPU host, on the laptop):

| Model | Dim | Query embed p50 (2 threads) | Rerank p50, top 10 / top 20 (2 threads) | Full-corpus embed (corpus v1: 1,861 chunks, all cores) |
|---|---|---|---|---|
| BAAI/bge-small-en-v1.5 | 384 | 5.4 ms | | 69.09 s |
| BAAI/bge-base-en-v1.5 | 768 | 15.8 ms | | 229.79 s |
| Xenova/ms-marco-MiniLM-L-6-v2 (reranker) | | | 205.9 / 546.4 ms (358.2 ms for top 20 with passages cut to 1,000 chars) | |
| BAAI/bge-reranker-base (reranker) | | | 922.3 / 2,119.7 ms | |

**Embedder (decided): BAAI/bge-small-en-v1.5 (384 dims) by default; bge-base-en-v1.5 is the upgrade when the host has the
RAM.**
- Retrieval quality: on the canonical set, hybrid MRR@10 / hit@5 was 0.736 / 0.87 with bge-small vs 0.745 / 0.89 with
  bge-base (§4.3). On MTEB retrieval, bge-small scores 51.68, close to OpenAI text-embedding-3-small at 51.08
  ([model card][bge-small], [stack report][r-stack]).
- Speed: bge-small embeds the corpus 3.3x faster (69.09 s vs 229.79 s, table above).
- Footprint: an image with fastembed and bge-small is 180 MB compressed and idles at 189 MiB RSS, against 73 MB and 59 MiB
  for a lean image without local models. Cold start to `/readyz` took 1.24-1.28 s ([stack report][r-stack]: docker build,
  `docker stats` with 1 CPU and 1 GiB). The POC API with bge-base plus MiniLM-L6 used 1,419 MB RSS after one query, and
  2,609 MB after a scorer run at concurrency 4, as the onnxruntime CPU memory arena grows with concurrent rerank batches
  (`poc/results/embed_probe.json`).
- Corpus vectors are computed offline into `embeddings.npy` and baked into the image. At about 10.6 chunks/s on 2 threads
  ([stack report][r-stack]) the corpus is far too slow to embed at startup. Only the query is embedded at runtime: 2.3 ms
  p50 in the stack bench, 5.4 ms at 2 threads in the POC.

**Reranker (decision R′): none in v1; FlashRank TinyBERT is the conditional upgrade.** On the canonical v1 set, the MiniLM-L6
rerank left MRR flat and lowered hit@3 and hit@5, and bge-reranker-base lowered MRR to 0.664 (§4.3;
`poc/results/retrieval-canonical.json`, and the log transcription `poc/results/retrieval-canonical-bge-reranker.json`). On
corpus v2, TinyBERT over the fused top 20 raised MRR@10 to 0.778 from 0.744 with hit@10 unchanged, while MiniLM-L6 and
bge-reranker-base stayed flat or worse (`poc/results/retrieval-v2.json`, §4.3). So v1 ships without a cross-encoder, and
checkpoint 2.7 switches `RERANK=tinybert` on only if it measures better on the event index. Measured costs:
- FlashRank TinyBERT-L-2: about 4 MB; 13.9 ms for 20 candidates and 41.7 ms for 50 ([stack report][r-stack]); 28.14 ms p50
  for the top 20 in the POC's corpus v2 bench (`poc/results/retrieval-v2.json`).
- fastembed MiniLM-L-6: 215 ms for 20 and 863 ms for 50 at low load ([stack report][r-stack]); 205.9 ms for the top 10 at
  2 threads (POC).
- bge-reranker-base: 922.3 ms for the top 10 at 2 threads, and about 1.5 GB more RSS (POC).

**Off-topic gate signal: the highest dense cosine (measured).** At 0 false abstains on the 82 must-answer rows it caught 7
of the 12 must-abstain rows, against 5 for TinyBERT, 4 for MiniLM-L6 and none for BM25 (`poc/results/gate-signals.json`,
§4.3). It reuses the query embedding, so the gate needs no extra model: `GATE_SIGNAL=dense`, no rewrite, and
`ABSTAIN_THRESHOLD=0.69` to start (the 0-false-abstain point 0.7126 minus a 0.02 margin), recalibrated at checkpoint 2.5.

### 5.4 Vector store
None. Retrieval stays in process. Stack-report benchmarks at 20k chunks:

| Engine | Query p50 at 20k chunks |
|---|---|
| bm25s | 0.10 ms |
| numpy exact cosine (384 / 768 dims) | 0.35 / 0.68 ms |
| FAISS flat | 0.24 ms |
| Chroma | 1.31 ms |
| sqlite-vec | 1.40 ms |
| SQLite FTS5 | 3.5 ms |
| LanceDB | 3.71 ms |
| rank_bm25 | 13.8 ms |

Our corpus is 961-1,742 chunks without the blog in the POC's corpus v2 (`poc/results/chunks.json`), or 1,039-2,158 more with the blog tier. Hosted vector services add a network hop, and
their free tiers pause when idle: Qdrant Cloud's after a week unused ([Qdrant][qdrant]), Supabase's after a week of
inactivity ([Supabase pricing][supabase]). Decision: bm25s plus numpy, fused with RRF. The index artifact is a directory
(plan section 0.2, I1).

### 5.5 Host

| Option | Role | Facts | Sources |
|---|---|---|---|
| Google Cloud Run, asia-south1 (Mumbai) | **Primary** | 41.5 ms HTTPS round trip from the venue area, against 261.7-387.9 ms to US and EU regions. With min-instances=1, idle cost is about $0.65 a day at the default 2 GiB, or $0.43 at 1 GiB (sizing below). `--source .` builds remotely, so no image upload over venue Wi-Fi. HTTP startup and liveness probes. `--no-cpu-throttling` keeps CPU for a background refresher. Needs a billing account | [stack report][r-stack] (gcping, pricing math); [Cloud Run pricing][cr-pricing]; [gcloud run deploy][gcloud-deploy]; [health checks][cr-health] |
| DigitalOcean App Platform, BLR | **Fallback** | BLR is available for dynamic apps. `apps-s-1vcpu-1gb` costs $12 a month and `apps-s-1vcpu-2gb` $25, billed per second, so one day costs well under $1. The app spec has `health_check` and `liveness_health_check`. Images must be AMD64 Linux; under 1 GiB is recommended. Traffic passes through Cloudflare. SSE buffering and a 100 s request cap appear only in community threads and are unverified, so the widget must be able to fall back to `POST /ask` | [availability][do-avail]; [pricing][do-app-pricing]; [app spec][do-spec]; [stack report][r-stack]; community threads on [SSE][do-sse] and [the 100 s limit][do-100s] |
| ngrok free dev domain, from the laptop | **Emergency** | One stable dev domain (`<name>.ngrok-free.app`); 1 GB a month outbound, 20,000 HTTP requests a month, 4,000 a minute. The browser interstitial applies to HTML pages only, not to API calls. SSE is not documented | [ngrok free plan][ngrok] |
| Cloudflare quick tunnel | Avoid | No SSE, a new random URL each run, and 200 in-flight requests at most | [quick tunnels][tunnel] |
| Fly.io | Avoid | No India region; a trial of 2 hours of machine runtime | [stack report][r-stack]; [Fly pricing][fly] |
| Render free | Avoid | Spins down when idle and serves a loading page | [Render free][render] |
| Hugging Face Docker Space | Only if PRO is already paid | Docker Spaces need a paid plan to create, and free hardware sleeps when unused. The container runs as uid 1000 on port 7860 | [Spaces overview][hf-overview]; [Docker Spaces][hf-docker] |

**Sizing (decided):** 1 vCPU, a request timeout of about 60 s, and min-instances 1. Memory: **2 GiB by default**, which
leaves headroom because the onnxruntime memory arena grows under bursts. **1 GiB is the minimum**, and it fits bge-small with
no reranker (189 MiB idle, [stack report][r-stack]). Use 4 GiB if the bge-base upgrade or a reranker experiment is enabled;
the POC measured 1.4-2.6 GB RSS with bge-base plus MiniLM (`poc/results/embed_probe.json`).

Idle cost with min-instances=1, at the idle rates of $0.0000025 per vCPU-second and per GiB-second
([Cloud Run pricing][cr-pricing], [stack report][r-stack]):

| Memory (1 vCPU) | Idle cost per day |
|---|---|
| 1 GiB | about $0.43 |
| 2 GiB (default) | about $0.65 |
| 4 GiB | about $1.08 |

The DigitalOcean fallback is sized the same way: `apps-s-1vcpu-2gb` ($25 a month) by default, `apps-s-1vcpu-1gb` ($12) at
the minimum, or a 4 GiB size such as `apps-d-1vcpu-4gb` ($49) ([pricing][do-app-pricing]). Add `--no-cpu-throttling` on Cloud Run when the in-app refresher
runs. On Cloud Run,
`--min-instances` is set per revision and `--min` service-wide. `--cpu-boost` is on by default for new services, and
`--update-secrets` maps env vars to Secret Manager versions ([gcloud run deploy][gcloud-deploy],
[Cloud Run secrets][cr-secrets]).

### 5.6 Widget pattern, CORS and CSP
**Prior art: Shadow DOM is the commercial norm.** kapa.ai and Inkeep both ship a single script that mounts a Shadow DOM
panel and streams with `fetch` and `getReader`, with no iframe. The stack research measured this from their bundles: kapa's is 2,130,950 bytes raw and
Inkeep's 1,655,186. olake.io sends no CSP and no `X-Frame-Options`, and its `/message-listener.js` accepts a
`{theme: light|dark}` message from a parent window when the docs are framed ([stack report][r-stack]). So both patterns
would work on olake.io itself, and Shadow DOM is an honest alternative there.

**Decision: the iframe loader stays primary**, with Shadow DOM as the documented alternative:
- one chat page serves as the full-page demo, the plain `<iframe>` embed and the launcher panel;
- nothing clashes with the host page's styles or keys (Docusaurus global CSS, the DocSearch Cmd+K shortcut);
- the iframe calls its own origin, so the host page needs no CORS or `connect-src` change.

A loader script injects a launcher and an iframe from our origin. `/embed` sends
`Content-Security-Policy: frame-ancestors *` so any site can frame it [[csp-fa]]. Docusaurus adds the loader through its
`scripts` config, which inserts tags into `<head>` [[docusaurus]]. Load it with `async: true`, because a script there
without async blocks rendering ([stack report][r-stack]). The loader watches `html[data-theme]` and posts the theme to the
iframe. Accessibility: `role=dialog`, a `role=log` message list ([MDN][log-role]), `aria-busy` while streaming, Escape to
close, focus restored to the launcher, and text rendered as text, never as raw HTML.

| | Loader plus iframe (chosen) | Shadow DOM widget (POC) |
|---|---|---|
| Style isolation | A separate document | Styles scoped to the shadow tree in both directions [[shadow-dom]] |
| What the host page's CSP must allow | `script-src` for `widget.js`, and our origin in `frame-src`, which falls back to `child-src` and then `default-src` [[frame-src]]. A plain iframe snippet needs only `frame-src` | `script-src` for `widget.js`, and our API origin in `connect-src`, because `fetch()` is governed by `connect-src`, which falls back to `default-src` [[connect-src]] |
| CORS | Not needed by the UI: the iframe calls its own origin | Needed: the host page calls our API from another origin |
| Access to the host page | None: messages only through `postMessage` | Runs in the host page's JavaScript context |

The POC tested this on a strict-CSP page (`poc/api/demo/csp.html`, `connect-src 'self'`) in Chrome
(`poc/results/embed_probe.json`). The Shadow DOM widget rendered, but `/ask` was blocked by a `connect-src` violation.
Because `fetch()` rejects with the same TypeError for CSP and CORS failures, the widget cannot tell the two apart. On an
ordinary page the same widget worked across origins, and a second request reused the cached preflight.

### 5.7 Production basics (decided)
- **FastAPI 0.135 or later**, for native SSE through `fastapi.sse.EventSourceResponse`. It works with POST, sets
  `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and sends a keep-alive ping every 15 s
  ([FastAPI SSE][fastapi-sse]).
- **CORS**: `allow_origins=*` without credentials, `max_age` 86400, and `x-request-id` exposed.
- **`/ask` always returns `{answer, sources}`**, even on errors, never an HTML 500. Bad input gets 422, FastAPI's validation
  default and our I2 contract, with the same JSON shape. The arch report suggests 400; clients would accept either.
- **Prompt-leak canary.** A random per-deploy token (`CANARY`, 16 hex characters) sits in the system prompt. An answer that
  contains it is replaced by the standard refusal (plus the real question's answer when one survives), the event is
  logged as `prompt_leak_blocked`, and the canary is never returned. It is a cheap deterministic output check, the kind of
  control OWASP LLM01 lists among its mitigations [[lit-owasp]]. It serves ADV-02, which asks for the system prompt
  verbatim.
- **Limits**: a per-client token bucket (the stack research suggests 60-120 per minute) with its burst capacity above the
  test-set size, because the scorer will probably send a burst from one IP; a global semaphore with a bounded wait
  (`QUEUE_WAIT_S`, about 20 s), after which `/ask` returns the degraded 200 answer, never a 503 or 429; and a daily
  token budget. Once the budget is spent, `/ask` returns the degraded answer (the most relevant pages, with sources), never
  a 429 or 5xx. The budget is raised before the scoring window if the credits allow.
- **Generation caps** (a POC production lesson). In JSON mode with no `max_tokens`, one local qwen3 request generated past
  6,000 tokens at 8 tok/s, held the only LLM slot, and cascaded timeouts through the concurrency-4 queue, with abandoned
  requests still holding the slot (`poc/README.md`, "Runaway generation"). So every call passes `max_tokens` (`MAX_TOKENS`,
  1500; it was 600 until the Opus 5.5 eval truncated 67 of 90 answers at that cap), and a truncation is logged. Answers
  averaged 72 completion tokens with prompt v1 and 6 passages
  (`poc/results/answer.json`), and 166.7 (p50 146) with prompt v3 and k=10. In that run one answer hit the 600-token cap, came back
  as truncated JSON and became a false abstain (SRC-03, `poc/results/eval_run-canonical-combined.json`). The event's answer is plain text with `[n]`
  citations and no JSON mode, so an unparseable or truncated answer gets one retry and is then salvaged: the validated,
  cited sentences are kept. The server's
  timeouts are shorter than any client's: `LLM_TIMEOUT_S` 25 s per call, and the whole `/ask` bounded at about 30 s with
  the queue wait included, after which it returns the degraded 200 answer.
- **Caching**: an in-process answer cache. It beats provider prompt caching for RAG, because Gemini 3.8 Flash needs a
  4,096-token identical prefix before caching applies ([Gemini caching][gem-caching], [stack report][r-stack]).
- **onnxruntime threads capped** (`ONNX_THREADS`, set to the vCPU count). By default every onnxruntime session sizes its
  thread pool to all cores; during the POC runs the load average went above 200 (`poc/README.md`, "Serving box").
- Pydantic validation (1-2000 characters), graceful degradation, structured JSON logs with `request_id`, `Server-Timing`,
  a non-root container user, and secrets only in env or Secret Manager.

### 5.8 Latency and cost targets
**Targets**: `/ask` p50 ≤ 3 s and p95 ≤ 6 s; stream time to first token ≤ 1.2 s; retrieval ≤ 150 ms on 2 vCPU. Measured so far:
- Hybrid retrieval with no reranker takes 13.53 ms p50 on all cores (§4.3), well inside the retrieval target. With a
  reranker it would not be: MiniLM-L6 takes 205.9 ms for the top 10 at 2 threads.
- The container reaches `/readyz` 1.24-1.28 s after start ([stack report][r-stack]).
- The generator's time to first token depends far more on its reasoning setting than on anything we control (§5.2).

**Hosted end-to-end latency: not measured on 2026-10-16 (no hosted key).**
- Estimate: p50 ≈ retrieval (about 14 ms) + the provider's time to first token (0.71-0.97 s for the fast non-reasoning
  candidates, several seconds or more with reasoning, §5.2) + about 167 output tokens at that model's speed (0.4-1.4 s at
  117-474 tok/s; the POC's round-2 mean with k=10, `poc/results/eval_run-canonical-combined.json`). That is about 1-2.5 s for a fast non-reasoning
  model, and more with reasoning.
- It is measured at the 12:30 checkpoint (plan section 5).

## 6. Evaluation

Method: [eval-questions.md](eval-questions.md). The POC scorer (`poc/eval/score.py`) checks the response schema
(exactly `answer` and `sources`), the source hit with normalized URLs, behaviour by question type (abstain or decline
where expected), latency p50 and p95, and must-mention fact coverage judged by an LLM.

**Why a custom scorer** (from the [arch-prior-art report][r-arch]): RAGAS needs the retrieved contexts and a reference,
and makes about 8 LLM calls per sample [[lit-ragas]]. DeepEval's RAG test cases also need the retrieval context
[[lit-deepeval]]. `POST /ask` returns only `answer` and `sources`. promptfoo can call `POST /ask` directly through its
HTTP provider [[lit-promptfoo-http]], but it caches results on disk by default, so live runs need `--no-cache`
[[lit-promptfoo-cli]]. A custom async scorer makes one judge call per question.

**Judge reliability.** GPT-4 as a judge agreed with humans over 80% of the time, but showed position, verbosity and
self-enhancement biases [[lit-mtbench]]. Only the largest judges align reasonably, and they are lenient [[lit-judges]].
Hamel Husain recommends binary labels and aligning the judge with human labels [[lit-hamel]]. So the eval uses a judge
from a different model family than the generator, at temperature 0, and hand-labels 10-15 items once to check agreement.
The POC adds one more reason: its local judge flipped 2 of 14 verdicts between thinking on and off (`poc/README.md`).

**The curated set** ([eval-questions.md](eval-questions.md)) has 94 rows:
- by type: 69 answerable, 5 negative, 4 false-premise, 4 adversarial, 6 out-of-scope, 6 unanswerable;
- by difficulty: 41 easy, 38 medium, 15 hard;
- 18 rows cite repo files or GitHub releases or issues ([`reports/eval-curated.json`](reports/eval-curated.json)).

The lead built it from the two research sets below in three steps:
- Independent adversarial verifiers checked both sets. They matched 258/258 evidence snippets on the ingestion set and
  corrected facts against the code ([verify-eval-ingestion](reports/verify-eval-ingestion.md)). On the ops set, all 43
  unique sources returned HTTP 200 and 243/243 key phrases matched ([verify-eval-ops](reports/verify-eval-ops.md)).
- The lead dropped 3 near-duplicates.
- The lead added 7 rows, checked on 2026-10-16. They target rendered-HTML-only content, a stale-page trap, a list question
  and freshness (REL-01, which must be re-checked on the morning of the event).

**Question sources:**
- [eval-ingestion report][r-eval-ingestion]: 40 questions (setup 7, sources 14, sync 11, destinations 8). 36 answerable and 4 negative, 20 easy /
  14 medium / 6 hard. 152 evidence quotes were checked against the fetched pages. 6 questions cite repo files, and 4 of
  those cannot be answered from the docs alone. A stdlib BM25 probe over 1,039 chunks put the best expected page at
  rank 1 for 31 of 40, in the top 3 for 36 and in the top 5 for 38.
- [eval-ops report][r-eval-ops]: 50 questions (catalogs 7, Fusion 8, deployment 7, troubleshooting 8, out-of-scope 6, unanswerable 6,
  false-premise 4, adversarial 4), 25 easy / 18 medium / 7 hard. 62 olake.io pages were fetched live, and 283 must-mention
  phrases were checked against their sources with none missing. For each unanswerable item, the answer was confirmed
  absent by searching the GitHub code, issues and releases and grepping the docs, blog and site source.

**POC results so far.** The seed set had 18 questions, 14 with expected sources (small and noisy). The curated set is
the 94 rows.
- Retrieval: the table in §4.3 (`poc/results/retrieval.json`).
- Answering (`poc/results/answer.json`, local qwen3:32b, so its latency says nothing about a hosted model): the answered
  questions hit an expected source 71.4% of the time. The abstain gate result is in §4.3. Retrieval took 13.7 ms p50 and the
  rerank 331.9 ms p50. On the local model's OpenAI-compatible API, only `reasoning_effort=none` turned thinking off: time to
  first token fell from 32,961 ms to 13,920 ms in the think probe. So set the hosted provider's lowest reasoning
  setting, and measure it at the 12:15 load test.
- **End to end on the curated 94 rows** (`poc/results/eval_run-canonical.json`): the POC API with the v1 prompt, a local
  qwen3:32b and the same model as judge, at concurrency 4. The run used the configuration from before decision R (the
  file's `config` block):
  - chunks: target 300, hard max 450; the docs plus repo allowlist v1; no blog (corpus v1);
  - retrieval: hybrid RRF k=60 over the BM25 top 50 and the dense top 50, with bge-base;
  - Xenova/ms-marco-MiniLM-L-6-v2 reranked the fused top 20 and was also the gate, at -0.891 (tuned on the seed set);
  - 6 passages to the LLM;
  - qwen3:32b Q4_K_M on ollama 0.33.3: temperature 0, JSON mode, `reasoning_effort` none, prompt v1;
  - the scorer at concurrency 4 with a 180 s timeout; the judge qwen3:32b with reasoning off, at concurrency 2;
  - default onnx threads (all 18 cores) on an Apple M5 Max that another onnxruntime job shared (load average above 200).

  Results:
  - Schema valid: 1.0.
  - Behaviour correct: 0.84.
  - Source hit: 0.695.
  - Fact coverage: 0.573.
  - Judged BEHAVIOR pass: 0.75.
  - Contradictions: 4.
  - 5xx responses: 0.
  - Abstain recall on unanswerable plus out-of-scope rows: 0.833, which **misses** the ≥ 0.90 target.
  - False-abstain on answerable rows: 0.072, which **misses** the ≤ 0.05 target.
  - Weakest types: false-premise (1 of 4), negative (2 of 5) and adversarial (2 of 4).
  - Where the false abstains came from (`abstain_breakdown`): 13 of the 82 must-answer rows abstained wrongly. On
    answerable rows alone it was 5 of 69 (gate 3, model 2).
    - The score gate: 7 (SET-07, SRC-11, SYNC-09, DEP-06, FP-03, ADV-02, ADV-03).
    - The model's answerable = false: 5 (SRC-08, SRC-09, SYNC-12, FP-02, FP-04).
    - The scorer's don't-know pattern on a sourced negative answer: 1 (SRC-16). Negative rows now skip abstain matching
      ([eval-questions.md](eval-questions.md#scoring-method)).
    - The no-valid-citation rule: 0. This decided D8 by data: abstain on zero valid citations.
  - Missed abstains: 2 of the 12 must-abstain rows, and the gate passed both. UNK-04 answered from the docs note that
    lists DLQ columns as "coming soon". OOS-03, a Debezium `snapshot.mode` question, got OLake's Strict CDC mode from the
    Postgres driver README with no decline.
  - What changes for the event: the gate becomes an off-topic short-circuit calibrated at 0% false abstains (§4.3). Brief
    B's prompt gets rules for negatives (SRC-08), "coming soon" features (UNK-04) and other tools' configuration
    (OOS-03). SYNC-12 (Postgres jsonb) is a retrieval fix: tables stay whole, plus the exact-match boost for identifiers.

  This run is a lower bound from a local 32B model; its latency (p50 105 s per `/ask`) says nothing about a hosted model.
  The event-day levers are listed in §4.3.
- **Prompt v2 A/B** (`poc/results/eval_run-canonical-v2-subset.json` against the same rows of the v1 run; 35 rows: all 25
  non-answerable plus 10 answerable; same retrieval and gate):
  - Behaviour correct rose from 23 to 26 of 35.
  - The judged false-premise BEHAVIOR check rose from 2 of 4 to 3 of 4.
  - Fact coverage was flat (0.533 vs 0.536 on the 23 judged rows).
  - FP-02 still accepted a false premise in v2. The deterministic rule only checks "did not abstain", so for false-premise
    rows trust the judged BEHAVIOR check (`poc/README.md`, finding 9b).

  The v2 rules go into the event prompt (plan section 4.3): correct false premises with the contradicting passage cited,
  answer the genuine question inside an injection, reply in the user's language, and add 2-3 few-shot premise corrections.
- **End to end with the round-2 policy** (`poc/results/eval_run-canonical-combined.json`, all 94 rows). The config, from the
  file's `config` block: corpus v2 with 300-token chunks; hybrid bge-small with no reranker; k=10 passages; a FlashRank
  TinyBERT top-10 gate below 0.3 with one rewrite (rewrite prompt v1); prompt v3; local qwen3:32b in JSON mode with
  reasoning off and `max_tokens` 600; the scorer at concurrency 1; qwen3:32b as the judge.
  **This is a measured proxy, not the exact recommended policy**: a close proxy of the recommended model stage. The
  differences: it ran JSON mode with an `answerable` flag, where the event generates plain text with the `NO_ANSWER` and
  `OUT_OF_SCOPE` markers; its prompt v3 has neither the plan's rule 5 sentence on other tools' configuration nor rule 15
  on "coming soon" features (`poc/answer/pipeline.py`); it ran a local qwen3:32b, where the event uses a hosted model;
  and its gate was TinyBERT plus a rewrite, where the recommended gate is the dense score with no rewrite. The gate-stage
  difference is measured offline in
  `poc/results/gate-rewrite.json`: the dense gate alone caught 7 of the 12 must-abstain rows at 0 false abstains (5 of 12
  at the 0.69 starting value).
  - Schema valid 1.0; 5xx 0; contradictions 4.
  - Behaviour correct 0.936 (0.84 in the v1 run); source hit 0.841 (0.695); fact coverage 0.603 (0.573); judged BEHAVIOR
    pass 0.85 (0.75).
  - False-abstain: 0.043 on answerable rows (3 of 69), which **meets** the ≤ 0.05 target; 0.049 on all must-answer rows
    (4 of 82).
  - Abstain recall on unanswerable plus out-of-scope rows: 0.833 (10 of 12), which still **misses** the ≥ 0.90 target.
  - Behaviour by type: negative 1.0 (5 of 5; 2 of 5 in v1); false-premise 1.0 (4 of 4 answered; 1 of 4 in v1), but judged
    BEHAVIOR passed only 2 of 4; out-of-scope 1.0 (6 of 6); adversarial 0.75 (3 of 4); unanswerable 0.667 (4 of 6);
    answerable 0.957.
  - Where abstains came from (the `X-Ask-Reason` header per row, and the file's `abstain_breakdown`): 8 declines by the
    gate after the rewrite, 4 model abstains and 2 unparseable answers. Of these, the must-abstain rows were declined 7
    times by the gate after the rewrite (all 6 out-of-scope rows and UNK-06) and 3 times by the model (UNK-01, UNK-03,
    UNK-05). The no-valid-citation rule caused none again.
  - False abstains (4):
    - SRC-03 and SYNC-03: unparseable JSON; SRC-03 had hit the 600-token cap;
    - SYNC-12: the model's answerable = false after a retrieval miss;
    - ADV-02: declined after the injectable rewrite (POC commit 6a48f4f). Its dense score is 0.815, so the recommended
      dense gate would pass it (`poc/results/gate-rewrite.json`).
  - Two of the 4 false abstains were JSON-parse failures. That supports the plan's plain-text generation with the
    `NO_ANSWER` and `OUT_OF_SCOPE` markers and `[n]` parsing, with no JSON mode (plan section 4.3).
  - Missed abstains (2): UNK-02 (TinyBERT gate score 0.994) and UNK-04 (0.73). Both answers cite the closest pages and miss
    the don't-know pattern, so the deterministic check counts them as answered. The judge passed both BEHAVIOR items: UNK-02
    says no AWS or Glue numbers are documented, and UNK-04 says no release date or version is given. So judged behaviour on
    the unanswerable rows was 6 of 6.
  - Local cost: the rewrite fired on 11 of 94 rows (p50 1,273.9 ms, about 196 tokens each). Generation over the 85 rows that
    called the LLM averaged 3,294 prompt tokens (p50 3,253, max 4,545) and 167 completion tokens (p50 146, max 600); 1 answer
    hit the cap. The whole run took 2,985 s; local latency is not representative (p50 25.7 s, p95 48.5 s).
  - Optional patch-hour ideas, both untested: strip injection-like sentences ("ignore … instructions", "print your system
    prompt", "no citations") before retrieval (`poc/README.md`), and a per-claim support check to lift recall on
    unanswerable rows.
- **Hosted end-to-end accuracy, latency and cost: not measured on 2026-10-16 (no hosted key).**
  - Estimate for latency: §5.8.
  - Estimate for cost per answer: about 3.3k input and 167 output tokens (the round-2 means above) times the provider's
    price. That gives about $0.0031 on gemini-3.8-flash ($0.75 / $3.75 per 1M) and about $0.0004 on DigitalOcean
    gpt-oss-120b ($0.10 / $0.70 per 1M) (§5.2).
  - Accuracy is expected to beat the local-32B lower bound above.
  - All three are measured at the 12:30 checkpoint.

Retrieval by category on corpus v2 is in §4.3: troubleshooting and sync-modes are the weakest categories, Fusion rows
retrieve well, and indexing the release notes moved REL-01 from rank 8 to 2.

> **Surprises from the POC** (`poc/README.md`, Findings; result files as named):
> - **Cross-encoders do not help on the canonical set.** bge-reranker-base costs 0.07 MRR (0.664 vs 0.736, a log
>   transcription), and MiniLM-L6 is neutral. The 14-question seed set said the opposite; its gains were noise
>   (`poc/results/retrieval-canonical.json`, §4.3).
> - **The rerank-score gate does not generalize** from the seed set to the 94 rows (§4.3, `poc/results/gate-canonical.json`).
> - **CPU embedding and reranking are the expensive steps, while generation tokens are small.** A rerank costs 0.2-2 s
>   and 0.5-1.5 GB of RAM; an answer averages about 1.86K prompt and 72 completion tokens with 6 passages, or 3.3K and 167 at k=10 (`poc/README.md`, findings 7, 8;
>   `poc/results/answer.json`).
> - **ollama ignores `/no_think`** and `extra_body={"think": false}` on its OpenAI-compatible API. Only
>   `reasoning_effort="none"` disables thinking (`poc/README.md`, finding 8).
> - **Nested Docusaurus tabs duplicate content.** Taking every tab panel emitted nested panels twice and inflated one page
>   from 122 KB to 342 KB of Markdown, until the extractor took only the panels of the current tab group. Brief A must
>   handle nested tabs (`poc/README.md`, finding 1).
> - **The docs repeat content** across `install/`, `getting-started/` and `fusion/install/`. So source hit undercounts
>   correct answers, and eval rows need alternate sources (`poc/README.md`, finding 10).
> - **The latencies were measured under heavy machine contention.** The load average went above 200 while another
>   onnxruntime job shared the machine, so they are inflated (`poc/results/eval_run-canonical.json` `config.machine_note`;
>   `poc/README.md`). Cap onnx threads on the server.

## 7. Prior art and what judges probe

### 7.1 Prior art

From the [arch-prior-art report][r-arch]. Each row links the original source.

| Project | What it does | What we take from it |
|---|---|---|
| [Ask Astro][pa-ask-astro] (Astronomer, Airflow docs; Apache-2.0) | Ingests docs, blog, GitHub PRs and StackOverflow into Weaviate. Per question: 2 LLM rewrites plus the original, up to 100 docs each, a Cohere rerank to 8, a relevancy check, then the answer. A curated question set reruns on every change. Hybrid plus rerank improved about 13.5% more answers, after embedding-only search missed the term "Astro SDK" ([blog][pa-ask-astro-blog]) | Exact product terms need lexical retrieval (BM25 plus the exact-match boost). Rerun the eval on every change (the plan's patch loop) |
| [DocsGPT][pa-docsgpt] (MIT; 18.3k stars) | A self-hosted assistant that cites sources, with guardrails against injection and ungrounded answers. The widget comes from one script tag or a React package ([widget docs][pa-docsgpt-widget]). The README describes no eval method | One script tag is the norm |
| [Onyx][pa-onyx] (formerly Danswer) | A hybrid vector plus keyword index, with a search-quality regression over ground-truth doc links ([README][pa-onyx-sq]) | A retrieval-only regression: the plan's `--retrieval-only` eval mode |
| [chat-langchain][pa-chatlc] | Now a managed deep agent that searches the docs. Its link checker follows redirects and checks for soft 404s ([link_check_tools.py][pa-chatlc-links]). Its guardrail test checks the prompt's wording only, with no LLM calls ([test_guardrails_scope.py][pa-chatlc-guard]) | Test behaviour with real calls, not prompt text. olake.io serves its redirect stubs (285 entries covering 305 legacy paths) with HTTP 200, so sources come only from chunk metadata |
| Supabase Clippy ([2023 post][pa-clippy]) | MDX sections in pgvector with a similarity threshold, a docs-only prompt and SSE streaming. Per-file checksums re-embed only changed docs ([template][pa-clippy-repo]) | Incremental rebuilds by content hash (the freshness design) |
| [Verba][pa-verba] (Weaviate), [AutoFlow][pa-autoflow] (PingCAP) | Verba is archived; its reranking was planned and never shipped. AutoFlow is a Graph RAG docs bot with an embeddable JS snippet | Nothing new for a one-day build |
| kapa.ai ([eval guide][pa-kapa-eval], [widget][pa-kapa-widget]) | Evaluates with about 100 real questions, 15-20% of them unanswerable. Factuality is graded A/B/C = 1/0.5/0 and uncertainty pass/fail, the indexed docs are frozen during an eval, and the judge is a top model with reasoning, repeated and watched for self-preference. The widget is one script tag, full screen on mobile, with an optional uncertain-answer callout | 12 of our 94 rows (12.8%) are unanswerable or out of scope, a little under kapa's share. Use the strongest judge (POC) |
| [Mintlify assistant][pa-mintlify], [Inkeep][pa-inkeep] | Mintlify says it doesn't have enough information, with an optional deflection email, and re-indexes on publish. Inkeep ships a Docusaurus plugin | Abstain with a next step (the unified short-circuit text, §4.3) |
| [Algolia DocSearch Ask AI][pa-algolia] | Enabled by an `askAi` assistant id. olake.io runs DocSearch without it (§3) | The judges' everyday baseline is keyword search |

**What the literature adds** (same report):
- **Insufficient context.** On questions whose context was insufficient, models hallucinated 15.4% (GPT-4o) to 40.4%
  (Gemini 1.5 Pro) of the time [[lit-suffctx]], and RGB's best negative-rejection rate was 45% [[lit-rgb]]. So the model's
  `NO_ANSWER` needs citation validation behind it.
- **Scoring abstains.** The CRAG benchmark scores a wrong answer -1 and "I don't know" 0 [[lit-cragbench]]: the same
  trade-off as our two abstain targets.
- **Citation support.** ALCE found that even the best models lack complete citation support half of the time on ELI5
  [[lit-alce]]. The server validates every `[n]`.
- **LLM judges.** See "Judge reliability" in §6.
- **Caching.** Semantic caches risk wrong-answer hits: GPTCache's README warns of false positives [[lit-gptcache]], and
  static similarity thresholds give no correctness guarantee [[lit-vcache]]. OLake questions differ in critical details
  (Postgres vs MySQL, Go vs Fusion), so the plan keeps an exact-match cache only.
- **Latency.** See the NN/g limits in §7.2.

### 7.2 What the rubric lets judges probe

Derived from the rubric text ([challenges page][ch]). These are the checks we should expect, not reports of what these judges did.

| Criterion (weight) | Likely probe | Our evidence |
|---|---|---|
| Answer accuracy (35) | Setup, configuration and troubleshooting questions across both products, including Fusion | Eval table by category; config blocks copied verbatim from cited chunks |
| Citations and honesty (15) | Do the sources support the answer? Unanswerable, out-of-scope and false-premise questions | Gate 2 citation validation; abstain triggers logged; abstain recall and false-abstain rate measured (§6) |
| Production readiness (20) | Bad input, bursts of requests, a slow or failing LLM, prompt injection, health endpoints, logs | 422 with an error shape; a queue instead of rejection; timeout, retry and fallback provider; injection rules; `/healthz` and `/readyz`; JSON logs with request IDs |
| UX and easy embedding (15) | Embedding on a foreign page with one line, mobile, keyboard use, readable citations | The loader plus iframe on any origin; demo page; source cards; mobile full screen |
| Engineering (15) | Index age, latency, cost per answer | `/healthz` manifest and UI footer; p50 and p95; tokens and cost per answer in logs; exact-match cache |

**Probes from published benchmarks.** The [arch-prior-art report][r-arch] maps each probe to a source:
- Unanswerable questions (kapa's 15-20%; RGB's negative rejection [[lit-rgb]]; MTRAG [[lit-mtrag]]): the UNK and OOS rows,
  and the abstain policy (§4.3).
- False premises (a CRAG question type [[lit-cragbench]]; FreshQA finds that all models struggle [[lit-freshqa]]): the FP
  rows and prompt rule 4.
- Version and deprecation facts (FreshQA): REL-01. The Postgres page says wal2json-based CDC is deprecated in favour of
  pgoutput.
- Go-vs-Fusion ambiguity (AmbigQA: over half of NQ-open is ambiguous [[lit-ambigqa]]). The report found 12 page pairs
  with 8-gram Jaccard ≥ 0.30, up to 0.95 (the Fusion and Go offline-environments-generic pages). Chunks carry `product`.
- Follow-up questions (MTRAG: 110 conversations of about 7.7 turns): `/ask` is single-turn (kickoff question K10), and
  multi-turn history is on the plan's cut list.
- Direct and indirect prompt injection (OWASP LLM01:2025 [[lit-owasp]]; promptfoo's RAG red-team plugins
  [[lit-promptfoo]]): the ADV rows and prompt rule 6.
- Citations that do not support the claim (ALCE [[lit-alce]]): citation validation.
- Stale links: olake.io's 285 redirect entries cover 305 legacy paths ([docs-site report][r-docs-site]; the arch report counts
  the same 285 entries), all answering HTTP 200, so a status-only link check passes stale URLs.
  Sources come only from chunk metadata.
- Latency and concurrency, empty or huge input, mobile layout, the one-line embed: practitioner judgement, backed by NN/g
  [[lit-nng]] and the kapa and DocsGPT widget defaults.
- NN/g's response-time limits: 0.1 s feels instant, 1 s keeps the user's flow, and after 10 s attention is lost; past 1 s,
  show that work is under way [[lit-nng]]. So the widget shows progress at once and streams tokens over SSE. First tokens
  within about 1 s is a target, not a measurement (§5.8).

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Credits throttle or stop during post-freeze scoring | Every row fails | The ordered provider chain: the credits, then the operator's paid key with ≥ 100 RPM (D7), then Gemma on the free tier, failing over before the first byte; a degraded mode that returns the most relevant pages; ask at kickoff (K1) |
| Endpoint down, cold or rate-limited while scoring | Production readiness and accuracy both lose | Min instances ≥ 1, a queue rather than rejection, a very high rate limit, a synthetic probe every minute (plan section 9) |
| The organizers match sources differently from us | Citation points lost | Canonical sitemap URLs and branch-form GitHub URLs; ask K3; matching in our own eval is lenient |
| Over-abstaining or under-abstaining | Accuracy or honesty points lost. Both abstain targets were missed in the local end-to-end run (recall 0.833, false-abstain 0.072; `poc/results/eval_run-canonical.json`) | The reranker score alone cannot separate the cases (§4.3), so the model's `NO_ANSWER` plus citation validation decides. The off-topic gate is a dense-score short-circuit with a 0.02 margin and no rewrite, with a unified short-circuit text; it catches 5 of 12 must-abstain rows (0.417) at the 0.69 starting threshold, and up to 7 of 12 at the zero-margin 0.7126, so the model does most of the abstaining. Event-day levers: a stronger hosted model, the unknowns fact card, the v2 prompt. In the round-2 proxy run false-abstain met the target (0.043) while recall stayed at 0.833 (§6); the final policy is measured at checkpoints 2.2 and 2.5 on the day |
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
| Docs tokens (o200k_base) | 264,265 | `poc/results/corpus.json` |
| Docs tokens per page (p50, max) | 1,152; 30,421 | `poc/results/corpus.json` |
| Blog tokens (85 posts) | 446,275 | `poc/results/corpus.json` |
| Allowlisted repo files and tokens (corpus v2, Tier A) | 38 files, 80,176 tokens. The measurements used allowlist v1: 84 files, 143,596 tokens | `poc/results/corpus.json` (v1 at POC commit 20b4bac) |
| Core index: docs, repo allowlist and release notes (corpus v2, no blog) | 196 documents, 353,043 tokens | `poc/results/corpus.json` (`combined_core_index`) |
| GitHub release notes indexed (the last 10 per repo) | 34 notes, 8,602 tokens; newest olake v0.12.1, olake-ui v0.7.1, olake-helm v0.4.0, olake-fusion v0.1.4 | `poc/results/corpus.json` (`releases`) |
| Fusion docs pages | 23 pages, 7 stubs, 28,391 tokens of content | `poc/results/corpus.json` (`fusion_pages`) |
| Fetch of 209 pages at concurrency 4 | 12.77 s (per page p50 0.243 s) | `poc/results/corpus.json` |
| Chunks at target 300 / hard max 450 (no blog) | 1,742 (docs 1,344, repo 350); tokens p50 226, p95 420, max 501; 3 over hard max | `poc/results/chunks.json` (corpus v2; the total includes 48 release-note chunks; 0 chunks mix two tabs) |
| Chunks at target 600 / hard max 900 (no blog) | 961 (docs 751, repo 175); tokens p50 420, p95 796, max 891; 0 over hard max | `poc/results/chunks.json` (corpus v2; the total includes 35 release-note chunks) |
| Blog tier chunks (target 300; target 600) | 2,158; 1,039 | `poc/results/chunks.json` (`blog_tier`) |
| Chunks at target 300 in corpus v1, behind every retrieval and eval number | 1,861 | `poc/results/retrieval.json` |
| Conditional GET to olake.io (304) | ≈ 12 ms | `poc/results/freshness.json` |
| `git ls-remote` per repo | 714-1005 ms | `poc/results/freshness.json` |
| GitHub API limit (unauthenticated, authenticated) | 60 per hour, 5,000 per hour | `poc/results/freshness.json` |
| Chunks over the bge 512-WordPiece limit (corpus v1) | 79 of 1,861 (target 300); 556 of 951 (target 600) | `poc/results/retrieval.json` |
| Retrieval MRR@10 / hit@5, 300-token chunks, 14 seed questions | BM25 0.451 / 0.714; hybrid bge-base 0.581 / 0.786; + MiniLM-L6 rerank 0.590 / 0.786; + bge-reranker-base 0.645 / 0.929 | `poc/results/retrieval.json` |
| Retrieval p50 (all cores) | hybrid bge-base 13.53 ms; + MiniLM-L6 rerank 431.29 ms; + bge-reranker-base 1,786.92 ms | `poc/results/retrieval.json` |
| Rerank p50 at 2 threads, top 10 | MiniLM-L6 205.9 ms; bge-reranker-base 922.3 ms | `poc/results/latency_threads.json` |
| Query embedding p50 at 2 threads | bge-small 5.4 ms; bge-base 15.8 ms | `poc/results/latency_threads.json` |
| Full-corpus embedding (corpus v1, 1,861 chunks) | bge-small 69.09 s; bge-base 229.79 s | `poc/results/retrieval.json` |
| Abstain gate on the top rerank score, seed set (18 rows) | threshold -0.891: precision 1.0, recall 1.0, false-abstain 0.0 (3 should abstain, 14 should answer) | `poc/results/answer.json` |
| Abstain gate, curated set (94 rows; 12 should abstain) | -0.891: recall 0.5, false-abstain 4.3% of answerable rows. Best threshold 1.18: recall 0.917, precision 0.44, false-abstain 13% of answerable and 17.1% of must-answer rows | `poc/results/gate-canonical.json` (the -0.891 figures recomputed from `per_question`) |
| Top rerank score range by type, curated set | answerable -2.67 to 7.78; unanswerable -5.52 to 6.28; out-of-scope -11.21 to 0.78; adversarial -6.36 to 2.95 | `poc/results/gate-canonical.json` (`by_type`) |
| Gate at 0 false abstains, corpus v2 (82 must-answer, 12 must-abstain rows) | recall: dense max cosine 0.583 (threshold 0.7126); TinyBERT top 10 0.417; MiniLM-L6 0.333; BM25 0 | `poc/results/gate-signals.json` |
| Dense gate at the 0.69 starting value | recall 0.417 (5 of 12), 0 false declines | `poc/results/gate-rewrite.json` |
| One LLM rewrite before the gate (local qwen3:32b) | p50 1,174.8 ms, p95 1,817.8 ms; 191.7 prompt and 11.9 completion tokens on average. At 0.71: recall 0.583 without it, 0.500 with it | `poc/results/gate-rewrite.json` |
| Retrieval on corpus v2 (82 rows), MRR@10 / hit@10 | no rerank 0.744 / 0.939; TinyBERT top 20 0.778 / 0.939 (rerank p50 28.14 ms); MiniLM-L6 top 20 0.742 / 0.939 (339.68 ms); bge-reranker-base top 20 0.649 / 0.915 (1,646.25 ms) | `poc/results/retrieval-v2.json` |
| Blog tier on corpus v2, MRR@10 | off 0.744; rank weight 0.5: 0.743; rank weight 1.0: 0.630 | `poc/results/retrieval-v2.json` |
| Retrieval by category, corpus v2 (MRR@10, no rerank) | catalogs 0.826; deployment 0.850; destinations 0.828; setup 0.750; source-config 0.738; sync-modes 0.674; table-maintenance 0.701; troubleshooting 0.597 | `poc/results/retrieval-v2.json` (`by_category`) |
| Uncapped generation in JSON mode (local qwen3) | one request past 6,000 tokens at 8 tok/s, holding the only LLM slot | `poc/README.md` ("Runaway generation") |
| Expected source among the 6 context passages, curated set (hybrid bge-base + MiniLM-L6) | 70 of the 82 rows with expected sources (85.4%) | `poc/results/gate-canonical.json` (`context_hit_rate_top_passages`) |
| Retrieval MRR@10 / hit@5 / hit@10, curated set (82 rows with sources, 300-token chunks) | BM25 0.680 / 0.854 / 0.915; hybrid bge-small 0.736 / 0.866 / 0.939; hybrid bge-base 0.745 / 0.890 / 0.927; hybrid bge-small + MiniLM-L6 0.746 / 0.829 / 0.939; hybrid bge-small + bge-reranker-base 0.664 / 0.829 / 0.890 (log transcription) | `poc/results/retrieval-canonical.json`; `poc/results/retrieval-canonical-bge-reranker.json` (log transcription) |
| API memory (hybrid bge-base + MiniLM-L6) | 1,419 MB RSS after one query; 2,609 MB after a scorer run at concurrency 4 | `poc/results/embed_probe.json` |
| Strict-CSP host page (`connect-src 'self'`) | The Shadow DOM widget renders, but `/ask` is blocked by `connect-src` | `poc/results/embed_probe.json` |
| Abstain on the model's own flag | precision 0.75, recall 1.0, false-abstain 0.071 | `poc/results/answer.json` |
| Answered questions that hit an expected source | 0.714 | `poc/results/answer.json` |
| Tokens per answer (6 passages) | prompt mean 1,858 (max 2,169); completion mean 71.8 (max 145) | `poc/results/answer.json` |
| Tokens per answer (k=10, prompt v3) | prompt mean 3,294 (p50 3,253, max 4,545); completion mean 166.7 (p50 146, max 600) | `poc/results/eval_run-canonical-combined.json` |
| End to end, round-2 proxy run (TinyBERT gate plus one rewrite; 94 rows, local qwen3:32b) | behaviour 0.936; source hit 0.841; fact coverage 0.603; abstain recall 0.833; false-abstain 0.043 on answerable rows, 0.049 on all must-answer rows; 5xx 0 | `poc/results/eval_run-canonical-combined.json` |
| Docs tokens from article text | 238,135 (o200k) | [docs-site report][r-docs-site], `measure_corpus.py` |
| Full docs fetch with gzip, 4 at a time | 2.07 MB in 2.2 s | [docs-site report][r-docs-site] |
| Pages whose content raw MDX misses | 22 of 124 | [docs-site report][r-docs-site], `hidden_content.py` |
| Anchors inside hidden tabs | 191 of 1,274 (15%) | [docs-site report][r-docs-site], `hidden_tab_headings.py` |
| Legacy paths answering 200 with a meta-refresh | 305 paths from 285 redirect entries | [docs-site report][r-docs-site] (redirect config in `main.js`); the [arch-prior-art report][r-arch] counts the same 285 entries |
| Docs deploys | 6 in about 26 h | [docs-site report][r-docs-site] (Actions runs API) |
| Docs release notes behind GitHub releases | 3-9 days (v0.8.0 to v0.12.0) | [olake-domain report][r-olake-domain] |
| BM25 hit@1/3/5 on 35 answerable seed questions | page level 18/26/29; chunk level 22/26/30; chunk level plus 3 rules 27/28/32 | [olake-domain report][r-olake-domain], `bm25_poc.py`, `bm25_rules.py` |
| Repo Tier A size | 377,136 bytes (about 94K tokens) | [repos report][r-repos] |
| spec.json converted to Markdown | 118,870 bytes to 39,612 bytes | [repos report][r-repos], `spec_to_md.py` |
| olake issues that are bot TODOs | 99 of 321 | [repos report][r-repos] |
| Grounded eval questions written | 40 (ingestion) + 50 (ops) | [eval-ingestion][r-eval-ingestion] and [eval-ops][r-eval-ops] reports |
| HTTPS round trip to Cloud Run regions (venue area) | Mumbai 41.5 ms; Delhi 53.4 ms; Singapore 53.0 ms; Iowa 261.7 ms; Belgium 360.2 ms; South Carolina 387.9 ms | [stack report][r-stack] (gcping, warm medians, n=7) |
| Cloud Run min-instance idle cost (1 vCPU) | 0.5 GiB about $0.324 a day; 1 GiB about $0.43; 2 GiB about $0.65; 4 GiB about $1.08 | [stack report][r-stack]; computed from the [Cloud Run pricing][cr-pricing] idle rates of $0.0000025 per vCPU-second and per GiB-second |
| Container image and idle memory | lean 73 MB / 59 MiB; with fastembed and bge-small 180 MB / 189 MiB | [stack report][r-stack] (docker save, docker stats) |
| Cold start to `/readyz` | 1.24-1.28 s | [stack report][r-stack] |
| Reranker latency, 20 / 50 candidates (low load) | FlashRank TinyBERT 13.9 / 41.7 ms; fastembed MiniLM-L-6 215 / 863 ms | [stack report][r-stack] |
| Cost per answer, 4k in and 400 out | $0.0004-$0.0045 (Gemini 3.8 Flash the highest) | [stack report][r-stack] (`cost.py`, list prices) |
| Widget bundles (prior art) | kapa 2,130,950 bytes, Inkeep 1,655,186 bytes; both Shadow DOM, no iframe | [stack report][r-stack] |
| End-to-end on the curated set, local qwen3:32b (v1 prompt, concurrency 4) | schema 1.0; behaviour 0.84; source hit 0.695; fact coverage 0.573; judged BEHAVIOR 0.75; contradictions 4; abstain recall 0.833 (target ≥ 0.90 missed); false-abstain 0.072 (target ≤ 0.05 missed); 0 5xx; p50 105 s per `/ask` (local model); wall time 2,646.5 s | `poc/results/eval_run-canonical.json` |
| Hosted end-to-end accuracy, latency and cost | Not measured on 2026-10-16 (no hosted key). Estimates: latency about 1-2.5 s p50 for a fast non-reasoning model (§5.8); cost about $0.0004-0.0031 per answer at 3.3k in and 167 out (§6). Measured at the 12:30 checkpoint | Method in §5.8 and §6 |

## Sources

[ev]: https://events.mlh.com/events/15468-hacktoberfest-hack-day-bengaluru-x-olake
[ch]: https://www.mlh.com/events/lakehouse-bot-day-hacktoberfest-bengaluru-x-olake/challenges
[r-docs-site]: reports/docs-site.md
[r-stack]: reports/stack.md
[gem-pricing]: https://ai.google.dev/gemini-api/docs/pricing
[gem-rl]: https://ai.google.dev/gemini-api/docs/rate-limits
[gem-caching]: https://ai.google.dev/gemini-api/docs/caching
[tilnote]: https://tilnote.io/pages/6a51b3398d9a59d14c1c174c
[mlh-do]: https://mlh.link/digitalocean
[do-limits]: https://docs.digitalocean.com/products/inference/details/limits/
[do-pricing]: https://docs.digitalocean.com/products/inference/details/pricing/
[do-inference-api]: https://docs.digitalocean.com/reference/api/reference/serverless-inference/
[groq-rl]: https://console.groq.com/docs/rate-limits
[aa]: https://artificialanalysis.ai/
[openai-readme]: https://raw.githubusercontent.com/openai/openai-python/main/README.md
[claude-compat]: https://platform.claude.com/docs/en/api/openai-sdk
[bge-small]: https://huggingface.co/BAAI/bge-small-en-v1.5
[qdrant]: https://qdrant.tech/documentation/cloud/create-cluster/
[supabase]: https://supabase.com/pricing
[cr-pricing]: https://cloud.google.com/run/pricing
[cr-health]: https://docs.cloud.google.com/run/docs/configuring/healthchecks
[cr-secrets]: https://docs.cloud.google.com/run/docs/configuring/services/secrets
[do-avail]: https://docs.digitalocean.com/products/app-platform/details/availability/
[do-app-pricing]: https://docs.digitalocean.com/products/app-platform/details/pricing/
[do-spec]: https://docs.digitalocean.com/products/app-platform/reference/app-spec/
[do-sse]: https://www.digitalocean.com/community/questions/feature-request-app-platform-supports-server-side-events
[do-100s]: https://www.digitalocean.com/community/questions/how-to-resolve-the-100s-request-timeout-of-digital-ocean-s-app-is-there-a-way-to-increase-the-timeout-or-something-else
[ngrok]: https://ngrok.com/docs/pricing-limits/free-plan-limits/
[fly]: https://fly.io/docs/about/pricing/
[render]: https://render.com/docs/free
[log-role]: https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/log_role
[fastapi-sse]: https://fastapi.tiangolo.com/tutorial/server-sent-events/
[r-repos]: reports/repos.md
[r-olake-domain]: reports/olake-domain.md
[r-eval-ingestion]: reports/eval-ingestion.md
[r-eval-ops]: reports/eval-ops.md
[r-arch]: reports/arch-prior-art.md
[pa-ask-astro]: https://github.com/astronomer/ask-astro
[pa-ask-astro-blog]: https://www.astronomer.io/blog/ask-astro-enhanced-retrieval-augmented-generation-cohere-rerank/
[pa-docsgpt]: https://github.com/arc53/DocsGPT
[pa-docsgpt-widget]: https://docs.docsgpt.cloud/Extensions/chat-widget
[pa-onyx]: https://github.com/onyx-dot-app/onyx
[pa-onyx-sq]: https://github.com/onyx-dot-app/onyx/blob/main/backend/tests/regression/search_quality/README.md
[pa-chatlc]: https://github.com/langchain-ai/chat-langchain
[pa-chatlc-links]: https://github.com/langchain-ai/chat-langchain/blob/master/src/tools/link_check_tools.py
[pa-chatlc-guard]: https://github.com/langchain-ai/chat-langchain/blob/master/tests/evals/test_guardrails_scope.py
[pa-clippy]: https://supabase.com/blog/chatgpt-supabase-docs
[pa-clippy-repo]: https://github.com/supabase-community/nextjs-openai-doc-search
[pa-verba]: https://github.com/weaviate/Verba
[pa-autoflow]: https://github.com/pingcap/autoflow
[pa-kapa-eval]: https://www.kapa.ai/blog/how-to-properly-evaluate-ai-assistants-for-technical-documentation
[pa-kapa-widget]: https://docs.kapa.ai/integrations/website-widget/configuration/legacy
[pa-mintlify]: https://www.mintlify.com/docs/assistant
[pa-inkeep]: https://docs.inkeep.com/integrations/docusaurus/chat-button
[pa-algolia]: https://docsearch.algolia.com/docs/v4/docsearch
[lit-contextual]: https://www.anthropic.com/news/contextual-retrieval
[lit-beir]: https://arxiv.org/abs/2104.08663
[lit-bruch]: https://arxiv.org/abs/2210.11934
[lit-dsrag]: https://github.com/D-Star-AI/dsRAG
[lit-selfroute]: https://arxiv.org/html/2407.16833
[lit-litm]: https://arxiv.org/abs/2307.03172
[lit-crag]: https://arxiv.org/html/2401.15884
[lit-suffctx]: https://arxiv.org/html/2411.06037
[lit-rgb]: https://arxiv.org/html/2309.01431
[lit-cragbench]: https://arxiv.org/html/2406.04744v2
[lit-alce]: https://arxiv.org/html/2305.14627
[lit-mtbench]: https://arxiv.org/abs/2306.05685
[lit-judges]: https://arxiv.org/abs/2406.12624
[lit-hamel]: https://hamel.dev/blog/posts/evals/
[lit-owasp]: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
[lit-promptfoo]: https://www.promptfoo.dev/docs/red-team/rag/
[lit-nng]: https://www.nngroup.com/articles/response-times-3-important-limits/
[lit-gptcache]: https://github.com/zilliztech/GPTCache
[lit-vcache]: https://arxiv.org/abs/2502.03771
[lit-freshqa]: https://arxiv.org/abs/2310.03214
[lit-mtrag]: https://arxiv.org/abs/2501.03468
[lit-ambigqa]: https://arxiv.org/abs/2004.10645
[lit-ragas]: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/
[lit-deepeval]: https://deepeval.com/docs/getting-started-rag
[lit-promptfoo-http]: https://www.promptfoo.dev/docs/providers/http/
[lit-promptfoo-cli]: https://www.promptfoo.dev/docs/usage/command-line/
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
[fus-pom]: https://github.com/datazip-inc/olake-fusion/blob/15ca160b298bf038f78f6639ec7aae67e4d4e33a/pom.xml
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
