Research agent output, 2026-10-16; evidence for docs/research.md

# olake-domain

## Summary
I mapped the OLake domain from the live docs (all 124 sitemap pages fetched and extracted), the four repo READMEs, the GitHub release APIs, Docker Hub and the Helm index, the Go driver source, and about 200 community-filed GitHub issues. The full report could not be saved as a file because the harness blocks report .md files from subagents, so it is in the findings below. The worktree was not touched; `git status` shows other people's changes to docs/plan.md and poc/*.

- **Components.**
  - OLake Go is a Go CLI with 8 drivers. Iceberg writes go through a Java gRPC writer (Iceberg 1.10.2) or a Go Arrow writer, and there is a Parquet writer.
  - OLake UI is a React frontend plus a Go BFF using Temporal and Postgres.
  - The OLake worker is a Temporal worker that lives in the olake-helm repo.
  - The Helm chart `olake` is at 0.0.30.
  - OLake Fusion is a modified Apache Amoro (incubating) pinned to Iceberg 1.7.2 and Spark 3.5.8. It appears in OLake UI 0.4.0 and later as the "Maintenance" module.
- **Latest releases (2026-10-16):** OLake Go v0.12.1 (10-15), UI v0.7.1 (10-15), worker v0.4.0 (10-08; Docker image pushed 10-15), chart 0.0.30 (10-08), Fusion v0.1.4 (08-24). The docs release notes stop at v0.12.0 and lag GitHub by 3–9 days.
- **Support matrix (checked in docs and Go code):**
  - Postgres, MySQL/MariaDB, MongoDB and MSSQL support all 4 modes.
  - Oracle and DB2 support only Full Refresh and Full Refresh + Incremental. DB2's `CDCSupported()` returns false in code. The README still calls Oracle CDC "WIP".
  - Kafka has a single mode (`strict_cdc`).
  - S3 supports Full Refresh and Incremental and is append-only.
  - Iceberg catalogs: Glue, Hive, JDBC, and REST (generic, Nessie, Polaris, Unity, Lakekeeper, S3 Tables, BigLake from v0.9.1, Horizon from v0.11.0). Parquet goes to S3, GCS, MinIO or local disk.
  - Fusion lists 9 catalogs and does not list BigLake or Horizon.
- **The docs corpus is small:** about 1.05M chars, roughly 262K tokens.
  - 18 pages are stubs. Some live pages are misleading: the Kafka overview still says "Coming Soon", and the connectors overview lists Kafka and S3 as WIP.
  - The Fusion architecture, terminology and engine pages are empty.
  - There is no published FAQ; the product pages carry FAQ JSON-LD instead.
- **First-party sources contradict each other.** The clearest case is Fusion's default schedule: 1h/8h/never on one page, 24h each on another, and 20m/40m on the product FAQ. Others:
  - `binlog_row_metadata=FULL` is called required, but v0.10.0 relaxed it.
  - The schema page says discovery runs every sync, but since v0.10.0 sync skips discovery unless `--discover-schema` is passed.
  - The schema page calls DATE→TIMESTAMP a v2 promotion; the Iceberg spec allows it only in v3+.
  - The README quickstart uses the legacy compose file.
  - A blog post uses the old `--catalog` flag.
- **Recurring user problems (15 found):** Postgres "LSN not updated" (open #1308), replica CDC, MySQL/MariaDB binlog and type issues, upsert duplicates, catalog configuration, air-gapped installs, K8s storage, stuck or cancelled jobs, discovery timeouts on large sources, Kafka pitfalls, MongoDB TLS and Cosmos DB, and Fusion operations. Most are only partly covered by the docs.
- **Freshness:** 25 docs commits in 30 days and 44 in 60. The sitemap `lastmod` is useless because a site rebuild on 10-06 touched 213 files. Open PRs may land around the event: streams v2 (#1145, splits streams.json), Azure ADLS for Iceberg, and MySQL switchover CDC. Re-crawl on 10-18.
- **Retrieval check:** plain BM25 found the right page in the top 3 for 26 of 35 seed questions. Three cheap rules raised that to 28, and top-1 hits from 22 to 27. The remaining misses are negative and overview questions, which hand-written fact cards would fix.
- **Outside sources:** 15+ upstream pages were opened and given precedence rules. Amoro is the riskiest because its defaults differ from Fusion's (128MB vs 512MB target size; snapshot expiry on upstream but disabled in Fusion v0.1.4).

## Recommendations
- **Index the 124 sitemap docs pages, but denylist or demote the stale and stub pages: /docs/connectors/overview/, /docs/connectors/kafka/overview/, /docs/tutorials/enable-oplogs/, /docs/archive/kubernetes/, the /docs/core/configs/* 'moved' stubs, and the Fusion 'Coming soon' pages. Add the /olake-go/ and /olake-fusion/ FAQ JSON-LD, live GitHub release notes for the 4 repos, the READMEs at low weight, and the 15 curated outside pages flagged outside_source=true. Treat the blog as optional and demoted.** — Live stale pages contradict current support: they say Kafka is 'coming soon' and S3 and Kafka are WIP. The product FAQs answer pre-sales questions the docs don't cover, and releases are newer than the docs. [evidence: https://olake.io/docs/connectors/kafka/overview/; https://olake.io/docs/connectors/overview/; https://olake.io/olake-fusion/; https://github.com/datazip-inc/olake/releases]
- **Hand-write fact cards, each linked to its canonical page: the source × mode matrix with explicit negatives, the destination × catalog × min-version matrix, the feature → min component versions table, a latest-versions table refreshed from the API, the unsupported-features list, and the known first-party contradictions.** — In the BM25 POC, negative and capability questions ('Oracle CDC?') and version questions retrieved old release notes. Fact cards fix these cheaply and support honest 'not supported' answers. [evidence: measured: BM25 POC misses Q02, Q30 (scripts/bm25_poc.py); https://olake.io/docs/connectors/oracle/; https://olake.io/docs/understanding/terminologies/olake/]
- **Chunk by H2/H3 and keep tab labels. Map REST-catalog tab content to ?rest-catalog=<generic|lakekeeper|nessie|s3-tables|unity|polaris|biglake|horizon> deep links. Canonicalize meta-refresh redirect URLs, and only emit citations that appear in the sitemap, GitHub or the curated outside list.** — 60% of tab panels are hidden on first load, so a citation to the bare page is hard to verify. Old URLs are 200-status meta-refresh stubs. [evidence: https://olake.io/docs/writers/iceberg/catalog/rest/?rest-catalog=horizon; https://olake.io/docs/understanding/compatibility-catalogs/; measured: 202 tab panels / 122 hidden; meta-refresh on /docs/connectors/postgres/overview/]
- **Rank retrieval with recency: demote release-note pages older than the latest two minors, route 'latest/version/release' questions to the GitHub releases API plus the newest docs release page, and date documents by olake-docs git commit date rather than sitemap lastmod.** — lastmod was reset by the 10-06 site rebuild (213 files). The docs release notes lag 3–9 days, and v0.12.1 is missing from them. [evidence: measured: git show --stat bc3013d; measured: release lag table; https://olake.io/docs/release/ingestion/v0.12.0/]
- **Re-crawl and re-index at startup and daily, plus a manual refresh on the morning of 2026-10-18. Show a 'docs as of <date>, latest release vX' line in version-sensitive answers.** — PRs that change config shape (streams v2), add storage options (ADLS) and change CDC behavior are open on staging. Fusion test-release images were pushed on 10-13. [evidence: measured: gh pr view 1145 -R datazip-inc/olake; measured: Docker Hub olakego/fusion test-next-release 2026-10-13]
- **Apply this source precedence: OLake docs, then GitHub release notes, then READMEs, product FAQ and blog (dated), then upstream vendor docs (only for that system, labeled), then Amoro (concepts only, labeled), then issues (only as 'known issue #N'). When OLake pages conflict, cite both.** — Fusion defaults conflict across three first-party pages. Amoro defaults differ from Fusion's (128MB vs 512MB; snapshot expiry). README and blog content is stale. [evidence: https://olake.io/docs/fusion/getting-started/configure-first-compaction/; https://olake.io/docs/fusion/compaction/configuration/; https://amoro.apache.org/docs/latest/configurations/; https://github.com/datazip-inc/olake]
- **Add an honesty path. Use a retrieval-score threshold with an explicit unsupported list: Oracle and DB2 CDC; Snowflake, BigQuery and DynamoDB sources; Fusion snapshot expiry and orphan cleanup undocumented; SSO; Fusion support for v3 DVs unknown. Point pricing and SLA questions to hello@olake.io or /contact/.** — The judges score citations and honesty at 15 points. The unanswerable seed question retrieved unrelated pages with BM25. [evidence: measured: BM25 top-3 for Q36 = mysql/setup/azure, kubernetes pages; https://olake.io/olake-go/; https://olake.io/contact/]
- **Use the 36 seed questions (data/eval_seed.json) as the start of the eval set. Add conflict-handling (Q19), honesty (Q02, Q03, Q20, Q29, Q36) and freshness (Q30) cases, and grow it from the 15 recurring GitHub issue themes.** — The seed set covers ingestion, Fusion, deployment, catalogs and troubleshooting, with gold URLs verified in this session. [evidence: measured: data/eval_seed.json; https://olake.io/docs/connectors/postgres/; https://olake.io/docs/fusion/compaction/types-of-compaction/]
- **For embedding, plan a script-tag widget or iframe that can be dropped into Docusaurus via a plugin or theme swizzle, without clashing with the existing Algolia DocSearch Cmd+K shortcut.** — The docs run Docusaurus 3.10.2 on GitHub Pages with no CSP header, so a third-party script or iframe is technically embeddable. [evidence: measured: curl -I https://olake.io/docs/ (no CSP), generator meta Docusaurus v3.10.2, algolia present]

## Measurements
- Docs URLs in sitemap: **124 of 275 total (matches lead)** (curl https://olake.io/sitemap.xml + python xml parse (scripts/sitemap.py))
- Docs pages fetched: **124/124 HTTP 200; 11,169,120 bytes HTML; avg 0.11 s** (sequential curl of sitemap docs URLs (data/pages-fetch.log))
- Docs corpus size (article text): **1,050,473 chars; 148,340 words; ~262K tokens (chars/4); median page 5,053 chars, p90 18,503, max 112,474 (REST catalog page)** (stdlib html.parser extraction of <article> (scripts/extract.py))
- Stub pages: **18 of 124 pages under 1,300 chars of article text** (extracted text length per page)
- Heading chunks: **1,193 H2/H3 chunks** (split extracted text on ##/### headings (scripts/bm25_poc.py))
- Tabbed content: **37 pages with tabs; 202 tab panels; 122 hidden by default** (regex count of role=tabpanel / hidden inside <article> across 124 pages)
- BM25 retrieval hit@1/3/5 on 35 answerable seed questions: **page-level 18/26/29; chunk-level 22/26/30; chunk+3 rules 27/28/32** (pure-Python BM25 (scripts/bm25_poc.py, scripts/bm25_rules.py) against data/eval_seed.json)
- olake-docs docs/ source size: **240 files, 1.38 MB; 225 md/mdx (1.30 MB); 111 shared partials** (gh api repos/datazip-inc/olake-docs/git/trees/master?recursive=1)
- Docs commits (docs/ path): **25 in last 30 days, 44 in last 60 days (whole repo: 101 / 157)** (git log --since on a blobless sparse clone of olake-docs)
- Monthly docs/ commits 2025-10..2026-10: **30,17,18,23,37,13,16,13,37,26,47,26,8 (Oct partial)** (git log --date=format:%Y-%m -- docs | uniq -c)
- Site rebuild blast radius: **commit bc3013d (2026-10-06) changed 213 docs files** (git show --stat bc3013d -- docs)
- Most-changed docs page in 60 days: **writers/iceberg/catalog/rest.mdx, 16 commits (excluding bc3013d)** (git log --name-only aggregation)
- Release counts last 30/60 days: **olake 6/11; olake-ui 5/7; olake-helm 3/5; olake-fusion 0/1** (gh api repos/datazip-inc/<repo>/releases published_at)
- Docs release-note lag behind GitHub release: **3–9 days (v0.8.0 5d, v0.9.0 6d, v0.10.0 9d, v0.11.0 3d, v0.12.0 5d); v0.12.1 not yet documented** (git log --diff-filter=A on docs/release/ingestion/*.mdx vs release published_at)
- Latest versions: **OLake Go v0.12.1 (2026-10-15); UI v0.7.1 (2026-10-15); worker v0.4.0 (GH 2026-10-08, Docker Hub 2026-10-15T06:11:50Z); chart 0.0.30 (2026-10-08, appVersion 0.3.11); Fusion v0.1.4 (2026-08-24)** (gh api releases; curl https://datazip-inc.github.io/olake-helm/index.yaml; Docker Hub tags API)
- Fusion/Writer Iceberg versions: **Fusion pom iceberg.version 1.7.2, spark.version 3.5.8, amoro-parent 0.9-SNAPSHOT; OLake Java writer version.iceberg 1.10.2** (curl raw pom.xml files + grep)
- GitHub issues (non-PR): **olake 321, olake-ui 87, olake-helm 24, olake-fusion 9, olake-docs 29; community-filed non-starter: 119/37/16/1/27 (=200)** (gh api --paginate repos/datazip-inc/<repo>/issues?state=all, filtered by author_association NONE/CONTRIBUTOR and labels)
- GitHub Discussions (olake): **7 total** (gh api graphql repository.discussions.totalCount)
- Repo metadata: **olake 1,556 stars / 182 open issues+PRs; olake-ui 34/90; olake-helm 15/32; olake-fusion 28/20; olake-docs 16/36; all Apache-2.0; Discussions only on olake** (gh api repos/datazip-inc/<repo>)
- Docs hosting: **GitHub Pages (server: GitHub.com), cache-control max-age=600, varnish; Docusaurus v3.10.2; Algolia DocSearch; no CSP header** (curl -I https://olake.io/docs/ ; grep generator/algolia in page HTML)
- LLM-friendly index: **llms.txt 22,607 bytes (152 lines); llms-full.txt 404; robots allows all except /*.json$** (curl https://olake.io/llms.txt, /llms-full.txt, /robots.txt)
- Docs pages with Troubleshooting sections: **32 pages; no published FAQ (docs/drafts/faqs.mdx draft; /docs/faq/ 404)** (grep '^## Troubleshooting' over extracted text; curl status checks)
- Docs semantic last-change distribution (current pages, excl. rebuild): **2026-10: 24, 2026-09: 13, 2026-08: 3, 2026-07: 2, 2026-06: 42, 2026-05: 6, 2026-04: 16, 2026-01: 2, 2025-10: 7, 2025-09: 7, 2025-08: 1, 2025-06: 2, 2025-01: 1 (126 files)** (git log --name-only, first non-bc3013d commit per existing .mdx (data/docs-last-substantive-current.txt))

## Findings
- [high] *component-map*: OLake has 2 products across 5 repos.
- OLake Go (datazip-inc/olake, Go, branch master) has 8 drivers: postgres, mysql (+MariaDB), mongodb, mssql, oracle, db2, kafka, s3. Each ships as image olakego/source-<driver>.
- CLI commands: spec, check, discover, sync, clear-destination.
- Iceberg writes use either the Java gRPC writer (version.iceberg 1.10.2, originally derived from debezium-server-iceberg) or the Go Arrow writer (arrow_writes flag); there is also a legacy writer. A Parquet writer exists too.
- OLake UI (datazip-inc/olake-ui) is a React 18/Vite/AntD UI on :8000 plus a Go BFF in server/ (Temporal SDK v1.39, GORM/Postgres). Swagger is at /swagger with session-cookie auth.
- The OLake worker lives in datazip-inc/olake-helm under worker/ (image olakego/ui-worker). It is a Temporal worker that runs Discover, Test, Sync, Fetch and Spec as Docker containers or K8s pods.
- Infrastructure: Temporal server 1.32.0 and Postgres 14-alpine, which stores configs, state and Temporal visibility. Elasticsearch is legacy only; MinIO backs S3 log storage.
- Helm chart 'olake' 0.0.30 adds fusion.enabled; NFS is deprecated.
- OLake Fusion (datazip-inc/olake-fusion) is a modified Apache Amoro (incubating): amoro-parent 0.9-SNAPSHOT, iceberg.version 1.7.2, spark.version 3.5.8. It runs an AMS management service plus a Spark optimizer (images olakego/fusion and olakego/fusion-spark).
- Fusion surfaces in OLake UI from v0.4.0 as 'Maintenance', enabled with Docker ENABLE_OPTIMIZATION=true --profile fusion or Helm fusion.enabled=true.
- The docs site (datazip-inc/olake-docs) is Docusaurus 3.10.2 on GitHub Pages with Algolia DocSearch. [evidence: https://github.com/datazip-inc/olake; https://github.com/datazip-inc/olake-ui; https://github.com/datazip-inc/olake-helm; https://github.com/datazip-inc/olake-fusion; https://olake.io/docs/install/kubernetes/; https://olake.io/docs/fusion/install/kubernetes-compaction/; https://olake.io/docs/api/olake-ui-api/; https://raw.githubusercontent.com/datazip-inc/olake-fusion/master/NOTICE; https://raw.githubusercontent.com/datazip-inc/olake-fusion/master/pom.xml; https://raw.githubusercontent.com/datazip-inc/olake/master/destination/iceberg/olake-iceberg-java-writer/README.md; https://raw.githubusercontent.com/datazip-inc/olake-helm/master/worker/README.md; https://raw.githubusercontent.com/datazip-inc/olake-helm/master/helm/olake/values.yaml; https://raw.githubusercontent.com/datazip-inc/olake-ui/master/server/go.mod; measured: drivers/ and destination/ dirs via gh api repos/datazip-inc/olake/git/trees/master?recursive=1]
- [high] *glossary-core-objects*: Core objects and files, with canonical URLs:
- OLake Go: the EL engine for DBs, Kafka and S3 into Iceberg or Parquet. https://olake.io/docs/
- OLake Fusion: Iceberg maintenance and compaction. https://olake.io/docs/fusion/getting-started/overview/
- OLake UI: :8000, default login admin/password. https://olake.io/docs/getting-started/quickstart/ and https://olake.io/docs/install/olake-ui/
- OLake worker: the Temporal activity runner. https://olake.io/docs/install/kubernetes/
- Driver: image olakego/source-<type>. https://olake.io/docs/install/docker-cli/
- Source, Destination and Job (active, inactive, saved or failed). https://olake.io/docs/understanding/terminologies/general/#1-source , #2-destination , #3-jobs
- Stream: a discovered table, collection, topic or S3 folder. https://olake.io/docs/understanding/terminologies/olake/#streams
- Namespace. https://olake.io/docs/install/docker-cli/#streams-config
- streams.json: selected_streams plus streams (type_schema, supported_sync_modes, cursor fields, destination_database). https://olake.io/docs/install/docker-cli/#streams-config ; the old page /docs/core/configs/catalog/ says 'moved'.
- source.json. https://olake.io/docs/core/configs/source/ plus the connector pages.
- destination.json (type ICEBERG or PARQUET). https://olake.io/docs/core/configs/writer/
- state.json: global holds the MySQL binlog position or Postgres LSN; per-stream chunks; MongoDB stores its _data resume token. https://olake.io/docs/install/docker-cli/#sync
- stats.json. https://olake.io/docs/install/docker-cli/#stats
- CLI flags: --config, --streams, --destination, --state, --discover-schema, --timeout (default 300s), --max-discover-threads (default 50), --destination-database-prefix. https://olake.io/docs/community/commands-and-flags/ [evidence: https://olake.io/docs/; https://olake.io/docs/understanding/terminologies/general/; https://olake.io/docs/understanding/terminologies/olake/; https://olake.io/docs/install/docker-cli/; https://olake.io/docs/community/commands-and-flags/; https://olake.io/docs/core/configs/catalog/; https://olake.io/docs/core/configs/state/]
- [high] *glossary-sync-semantics*: Sync semantics, with canonical URLs:
- Sync modes. The UI shows Full Refresh, Full Refresh + Incremental, Full Refresh + CDC and CDC Only; the config values are full_refresh, incremental, cdc and strict_cdc (types/sync_mode.go). Changing a stream's mode triggers Clear Destination. https://olake.io/docs/understanding/terminologies/olake/#2-sync-modes
- Full Refresh is always written as Append. https://olake.io/docs/understanding/terminologies/general/#40-full-refresh
- Incremental: a primary cursor is required and a secondary is optional. An auto-increment cursor misses updates, and deletes are never captured. https://olake.io/docs/understanding/terminologies/olake/#2-sync-modes
- CDC is log-based and runs per scheduled sync, not as an always-on stream. https://olake.io/docs/understanding/terminologies/general/#39-change-data-capture
- Strict CDC ('CDC Only') skips the initial load.
- Backfill / initial snapshot: snapshot rows get _op_type r and an epoch _cdc_timestamp. Backfill is not formally defined. https://olake.io/docs/understanding/terminologies/general/#4-snapshot
- Chunking. https://olake.io/docs/understanding/terminologies/general/#6-chunking
- Max threads: the connection limit is per job. https://olake.io/docs/#3-configurable-max-connections
- Normalization: level-1 JSON flattening. https://olake.io/docs/understanding/terminologies/olake/#1-normalization
- Data filter: up to 2 conditions; requires normalization; changing it triggers Clear Destination. https://olake.io/docs/understanding/terminologies/olake/#3-data-filter
- Upsert (default) vs Append (Kafka default) via append_mode. https://olake.io/docs/understanding/terminologies/olake/#7-modes-to-ingest-data-upsert-vs-append
- update_type: eq (equality, v2), pos (positional, v2) or dv (deletion vectors, v3). Positional and DV need the Pebble index DB; Kafka supports pos only. https://olake.io/docs/understanding/terminologies/olake/#upsert
- Target Query Engines, UI 0.6.0+. https://olake.io/docs/getting-started/job-level-properties/#target-query-engines
- Kafka dedup keys. https://olake.io/docs/connectors/kafka/
- Generated columns: _olake_id (the PK, a PK hash, or an all-column hash when there is no PK), _op_type r/c/u/d, _olake_timestamp, _cdc_timestamp, plus _cdc_lsn, _cdc_binlog_file_name/_pos, _cdc_resume_token, and _cdc_start_lsn/_cdc_seqval. https://olake.io/docs/understanding/terminologies/general/#4-olake-go-generated-columns
- Partition regex '/{field, transform}'. https://olake.io/docs/writers/iceberg/partitioning/
- Schema evolution and type promotion. https://olake.io/docs/features/schema/
- Destination database 'jobname_database_{namespace}', dynamic or custom. https://olake.io/docs/understanding/terminologies/olake/#destination-database
- Clear Destination. https://olake.io/docs/getting-started/job-level-properties/#8-clear-destination
- Two-phase commit. https://olake.io/docs/#8-two-phase-commit
- Iceberg catalog. https://olake.io/docs/understanding/terminologies/general/#14-catalog
- Postgres replication slot and publication: unique per job. https://olake.io/docs/connectors/postgres/
- WAL, binlog and oplog. https://olake.io/docs/understanding/terminologies/general/#24-wal-write-ahead-log [evidence: https://olake.io/docs/understanding/terminologies/olake/; https://olake.io/docs/understanding/terminologies/general/; https://olake.io/docs/getting-started/job-level-properties/; https://olake.io/docs/writers/iceberg/partitioning/; https://olake.io/docs/features/schema/; https://raw.githubusercontent.com/datazip-inc/olake/master/types/sync_mode.go]
- [high] *glossary-fusion*: Fusion terms:
- Lite compaction merges small 'fragments' and converts equality deletes to positional deletes.
- Medium compaction merges 'segments' toward the target size and applies deletes. Output files fall between 1/8 of the target size and the target size.
- Full compaction rewrites everything into target-size files (copy-on-write).
- Precedence is Full > Medium > Lite.
- Default target file size is 512 MB.
- Health Score = Small Files 40% + Eq Delete 40% + Pos Delete 20%.
- A Run is one compaction execution with status Running, Success, Failed, Cancelled or Skipped. Runs have driver logs, sub-task logs and run metrics.
- Catalogs are either 'OLake Imported' (taken from an ingestion destination) or 'External'. For JDBC, the catalog name must match the one used at ingestion; the default is olake_iceberg.
- Conflict-free compaction of OLake-written tables needs OLake Go v0.7.0 or later. [evidence: https://olake.io/docs/fusion/compaction/types-of-compaction/; https://olake.io/docs/fusion/compaction/configuration/; https://olake.io/docs/fusion/getting-started/configure-first-compaction/; https://olake.io/docs/fusion/maintenance/runs-and-logs/; https://olake.io/docs/fusion/maintenance/catalogs/; https://olake.io/docs/fusion/maintenance/metrics/]
- [high] *support-matrix-sources*: Sources × sync modes (FR / FR+Incremental / FR+CDC / CDC Only), as of v0.12.1:

| Source | Modes | CDC mechanism / notes | Min version |
|---|---|---|---|
| Postgres | all 4 | pgoutput (wal2json deprecated) | PG 10+ |
| MySQL / MariaDB | all 4 | binlog with ROW format | MySQL 5.7+ |
| MongoDB | all 4 | change streams over oplog; needs a replica set | 4.0+ |
| MSSQL | all 4 | SQL Server CDC tables; 3-day retention | 2017+ |
| Oracle | FR and FR+Incremental only, no CDC | — | 11g+ (tested 19c and 23ai) |
| DB2 LUW | FR and FR+Incremental only, no CDC | not supported on linux/arm64 | 11.5.3+ |
| Kafka | single mode (strict_cdc), reads to the latest offset | consumer group per job; JSON or Avro, Avro needs a schema registry; Append default, Upsert needs Go 0.12.1+ / UI 0.7.1+ | Kafka 2.4.0+; OLake v0.3.0+ |
| S3 | FR and FR+Incremental (LastModified cursor) | CSV, JSON/JSONL, XML, Parquet, gzip; one stream per top-level folder; append-only, enforced in v0.12.1 (#1263) | — |

The docs overview, the connector pages and the Go code agree on this. In code, Oracle declares only FULLREFRESH and INCREMENTAL, DB2's CDCSupported() returns false, and Kafka declares only STRICTCDC. [evidence: https://olake.io/docs/; https://olake.io/docs/connectors/postgres/; https://olake.io/docs/connectors/mysql/; https://olake.io/docs/connectors/mongodb/; https://olake.io/docs/connectors/mssql/; https://olake.io/docs/connectors/oracle/; https://olake.io/docs/connectors/db2/; https://olake.io/docs/connectors/kafka/; https://olake.io/docs/connectors/s3/; https://raw.githubusercontent.com/datazip-inc/olake/master/drivers/db2/internal/db2.go; https://raw.githubusercontent.com/datazip-inc/olake/master/drivers/oracle/internal/oracle.go; https://github.com/datazip-inc/olake/releases/tag/v0.12.1]
- [high] *support-matrix-destinations*: Iceberg catalogs and storage:
- Glue on S3.
- Hive on S3, MinIO or GCS. The GCS Iceberg page says GCS works via Hive only.
- JDBC on S3 or MinIO.
- REST: generic, Lakekeeper (S3 and ADLS Gen2 via the Azure guide), Nessie, Polaris (with an IAM setup page), Unity (managed tables only), S3 Tables (REST with SigV4), BigLake (v0.9.1+, GCS) and Snowflake Horizon (v0.11.0+). The REST page uses deep links ?rest-catalog=generic|lakekeeper|nessie|s3-tables|unity|polaris|biglake|horizon.
- Parquet goes to S3, GCS (HMAC keys through the S3 API), MinIO or the local filesystem, with max file size defaulting to 512MB.
- Fusion lists Glue, REST generic, Nessie, Polaris, Unity, Lakekeeper, S3 Tables, JDBC and Hive. BigLake and Horizon are not listed.
- The README catalog list is stale: it omits BigLake and Horizon. [evidence: https://olake.io/docs/understanding/compatibility-catalogs/; https://olake.io/docs/writers/iceberg/catalog/glue/; https://olake.io/docs/writers/iceberg/catalog/hive/; https://olake.io/docs/writers/iceberg/catalog/jdbc/; https://olake.io/docs/writers/iceberg/catalog/rest/?rest-catalog=horizon; https://olake.io/docs/writers/iceberg/catalog/rest/?rest-catalog=biglake; https://olake.io/docs/writers/iceberg/azure/; https://olake.io/docs/writers/iceberg/gcp/; https://olake.io/docs/writers/parquet/config/; https://olake.io/docs/writers/parquet/gcs/; https://olake.io/docs/fusion/maintenance/catalogs/; https://github.com/datazip-inc/olake]
- [high] *support-matrix-engines*: The compatibility-engines page has two matrices: 20 engines × 10 catalogs, and engines × delete formats. Key rows:
- Snowflake GA cannot read equality deletes; it reads positional deletes and deletion vectors.
- Databricks outside Spark reads only deletion vectors.
- Athena, Presto, Hive 4.2, Impala, StarRocks and Redshift cannot read deletion vectors.
- Dremio supports deletion vectors on Dremio Cloud only.
- Athena reads only Glue and S3 Tables catalogs.
AWS docs agree that Athena only operates on Iceberg v2, uses the Glue catalog only, and has millisecond timestamp precision. Horizon is not a column in the engine matrix. [evidence: https://olake.io/docs/understanding/compatibility-engines/; https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html]
- [high] *version-matrix*: Minimum versions are scattered across pages (worth a fact card):

| Feature | OLake Go | UI | Other |
|---|---|---|---|
| Kafka source | 0.3.0 | — | — |
| CDC position columns | 0.3.16 | — | — |
| Column selection | 0.4.0 | 0.3.1 | — |
| Data filter on CDC and incremental | 0.6.0 | 0.4.1 | — |
| Conflict-free Fusion compaction | 0.7.0 | — | Maintenance module needs UI 0.4.0 |
| Source naming convention | 0.7.7 | 0.4.7 | — |
| BigLake catalog | 0.9.1 | — | — |
| Positional deletes | 0.10.0 | — | — |
| Delete formats eq/pos/dv | 0.11.0 | 0.6.0 | worker 0.3.11, chart 0.0.28 |
| Horizon catalog | 0.11.0 | — | — |
| S3 log/config storage | 0.12.0 | 0.7.0 | worker 0.4.0, chart 0.0.30 |
| Kafka upsert | 0.12.1 | 0.7.1 | — | [evidence: https://olake.io/docs/understanding/terminologies/olake/; https://olake.io/docs/understanding/terminologies/general/; https://olake.io/docs/connectors/kafka/; https://olake.io/docs/install/kubernetes/; https://olake.io/docs/install/olake-ui/; https://olake.io/docs/fusion/getting-started/overview/; https://olake.io/docs/fusion/getting-started/configure-first-compaction/; https://olake.io/docs/release/ingestion/v0.10.0/; https://olake.io/docs/release/ingestion/v0.11.0/]
- [high] *latest-versions*: Latest versions and where the notes live:

| Component | Latest | Date | Notes |
|---|---|---|---|
| OLake Go | v0.12.1 | 2026-10-15 | v0.12.0 on 10-07, v0.11.3 on 10-05 |
| OLake UI | v0.7.1 | 2026-10-15 | — |
| OLake worker (olake-helm v* tags) | v0.4.0 | GitHub 2026-10-08 | Docker Hub olakego/ui-worker:v0.4.0 pushed 2026-10-15T06:11:50Z, about 4h after olake-helm#231 reported it missing |
| Helm chart olake | 0.0.30 | index created 2026-10-08 | appVersion 0.3.11 |
| OLake Fusion | v0.1.4 | 2026-08-24 | 'Snapshot Expiry fixed'; images fusion and fusion-spark v0.1.4 |

Release notes live in two places:
- The docs. OLake Go: https://olake.io/docs/release/ingestion/overview/ (one page per minor version, patches folded in; the newest is the v0.12.0 page). Fusion: https://olake.io/docs/fusion/release/maintenance/overview/ (one page, v0.1.0–v0.1.4).
- GitHub release pages for each repo.

Connector pages also carry a 'Changelog' table whose last entry (v0.1.11, Aug 2025) is stale. Docker Hub shows olakego/fusion:test-next-release pushed 2026-10-13, which hints at an upcoming Fusion release. [evidence: https://github.com/datazip-inc/olake/releases/tag/v0.12.1; https://github.com/datazip-inc/olake-ui/releases/tag/v0.7.1; https://github.com/datazip-inc/olake-helm/releases/tag/v0.4.0; https://github.com/datazip-inc/olake-fusion/releases/tag/v0.1.4; https://datazip-inc.github.io/olake-helm/index.yaml; https://olake.io/docs/release/ingestion/v0.12.0/; https://olake.io/docs/fusion/release/maintenance/v0.1.0/; https://github.com/datazip-inc/olake-helm/issues/231; measured: gh api repos/datazip-inc/<repo>/releases published_at; Docker Hub API hub.docker.com/v2/repositories/olakego/<img>/tags]
- [high] *freshness-release-lag*: Docs release-note pages appear 3–9 days after the GitHub release (median 5). The v0.12.1 notes (Kafka upsert, CDC prerequisite checks in test connection, S3 append enforcement, MariaDB binlog flavor, digits allowed in catalog names, TOAST-aware ctid chunks) were not in the docs on 2026-10-16. Connector pages already require v0.12.1 for Kafka upsert.

| Version | GitHub release | Docs page created |
|---|---|---|
| v0.8.0 | 07-03 | 07-08 |
| v0.9.0 | 07-24 | 07-30 |
| v0.10.0 | 09-07 | 09-16 |
| v0.11.0 | 09-25 | 09-28 |
| v0.12.0 | 10-07 | 10-12 | [evidence: measured: git log --diff-filter=A on docs/release/ingestion/*.mdx (blobless clone of olake-docs) vs gh api releases published_at; https://github.com/datazip-inc/olake/releases/tag/v0.12.1; https://olake.io/docs/connectors/kafka/]
- [high] *docs-gap-1-postgres-lsn*: Recurring problem: Postgres CDC stops with the non-retryable 'LSN not updated after X mins'. Issues: olake#1308 (open, 2026-10-13, walsender killed during a ~30s Iceberg commit), #862, #853. The docs partly answer it: troubleshooting §3 says to set wal_sender_timeout to 0 or a large value. PostgreSQL's own default for wal_sender_timeout is 60s, and 0 disables the timeout. [evidence: https://github.com/datazip-inc/olake/issues/1308; https://olake.io/docs/connectors/postgres/; https://www.postgresql.org/docs/current/runtime-config-replication.html]
- [high] *docs-gap-2-postgres-replica*: Recurring problem: Postgres CDC from a read replica or across failover. Issues: olake#1069 (pg_current_wal_lsn errors during recovery) and olake-docs#6 'Replica Mode' (open). The docs partly answer it: a 'Read Replica Support' note says PG16+ works with limitations and recommends the primary. There is no failover or slot-sync guidance; the upstream PG docs cover logical decoding on a standby (hot_standby_feedback). [evidence: https://olake.io/docs/connectors/postgres/setup/generic/; https://olake.io/docs/connectors/postgres/setup/rds/; https://www.postgresql.org/docs/current/logicaldecoding-explanation.html; measured: issue list via gh api repos/datazip-inc/olake/issues?state=all (olake#1069)]
- [high] *docs-gap-3-postgres-deletes-toast*: Recurring problem: deletes keep only the primary key, and TOAST columns arrive null on updates. Issues: olake#984, #1175, #1176; PR #1264 adds TOAST resolution. The docs answer it: troubleshooting §4–5 recommend ALTER TABLE ... REPLICA IDENTITY FULL. [evidence: https://olake.io/docs/connectors/postgres/; https://www.postgresql.org/docs/current/sql-altertable.html; measured: gh api issues listing; gh pr list -R datazip-inc/olake]
- [high] *docs-gap-4-mysql-cdc*: Recurring problem: MySQL and MariaDB CDC failures. The docs partly answer it: the MySQL page covers 'Failed to Get Current Binlog Position', 'Idle Timeout', 'Column Count Mismatch', chunk split failures and the timezone error. Not documented:
- the MariaDB GTID error 1236 (olake#1292), fixed in v0.12.1 via the MariaDB binlog flavor;
- the v0.10.0 change allowing CDC without binlog_row_metadata=FULL. The connector page still lists FULL as required, while MySQL 8.4's own default is MINIMAL. [evidence: https://olake.io/docs/connectors/mysql/; https://olake.io/docs/release/ingestion/v0.10.0/; https://github.com/datazip-inc/olake/releases/tag/v0.12.1; https://dev.mysql.com/doc/refman/8.4/en/replication-options-binary-log.html]
- [high] *docs-gap-5-mysql-types-tz*: Recurring problem: MySQL type and time handling. Issues:
- TIMESTAMP values shift in CDC when the server timezone is not UTC (olake#811, 13 comments);
- INT UNSIGNED (#842), DECIMAL (#693), ENUM in CDC (#707, #876), BINARY (#1031, open), 0000-00-00 dates (#570).
The docs partly answer it with the timezone troubleshooting entry, a data-type mapping and a date/time handling section. BINARY handling is still pending in docs PR #528 and olake PR #1137. [evidence: https://olake.io/docs/connectors/mysql/; measured: gh api repos/datazip-inc/olake/issues/811; gh pr list -R datazip-inc/olake-docs (PR #528 open)]
- [high] *docs-gap-6-upsert-duplicates*: Recurring problem: Iceberg upsert writes duplicates or unexpected delete files. Issues:
- arrow_writes=true broke CDC dedup (olake#1189, closed 2026-09-18);
- re-inserting a deleted PK leaves the soft-deleted row live with pos/dv deletes (#1286, open);
- S3 incremental streams were treated as upsert because append_mode was omitted (#1237, open; v0.12.1 enforces append for S3).
The docs do not cover these failure modes. The upsert semantics are documented, and the fixes appear only in release notes (v0.10.0 'Fixed CDC deduplication'). [evidence: https://github.com/datazip-inc/olake/issues/1189; https://github.com/datazip-inc/olake/issues/1237; https://olake.io/docs/understanding/terminologies/olake/#upsert; https://olake.io/docs/release/ingestion/v0.10.0/]
- [high] *docs-gap-7-engine-compat*: Recurring question: a query engine cannot read OLake tables because of the delete-file format. The docs answer it with the engine × delete-format matrix and the Target Query Engines job setting, which narrows the formats offered to those every chosen engine can read. [evidence: https://olake.io/docs/understanding/compatibility-engines/; https://olake.io/docs/getting-started/job-level-properties/#target-query-engines]
- [medium] *docs-gap-8-catalog-config*: Recurring problem: catalog configuration errors.
- Nessie REST URI hardcoded to v1 (olake#620).
- JDBC catalog name for Trino (#681).
- Digits rejected in catalog names (#1032, fixed in v0.12.1 via #1184).
- Lakekeeper credential vending (#859) and ADLS on Lakekeeper (#589).
- REST + MinIO 'security token invalid' (#389, 33 comments).
The docs partly answer it with per-catalog troubleshooting and the local-testing page. The REST page's 'only lowercase letters and underscores' rule for catalog names is probably stale after v0.12.1. [evidence: https://olake.io/docs/writers/iceberg/catalog/rest/; https://olake.io/docs/writers/iceberg/troubleshooting-local/; https://github.com/datazip-inc/olake/issues/389; https://github.com/datazip-inc/olake/issues/681; https://github.com/datazip-inc/olake/releases/tag/v0.12.1]
- [high] *docs-gap-9-airgapped*: Recurring problem: air-gapped and private-registry deployments.
- The UI version fetch blocks source creation (olake-ui#340, open, 18 comments; #339).
- Docker Hub coupling (olake-ui#380).
- Registry Access Management (olake#1253).
- Custom CA 'certificate signed by unknown authority' (olake#1254).
- Helm cert injection not working (olake-helm#180).
The docs partly answer it with offline-environment guides and private-registry sections. CA and cert injection are undocumented, and olake PR #1296 'added-cert-file-support' is open. [evidence: https://github.com/datazip-inc/olake-ui/issues/340; https://olake.io/docs/install/olake-ui/offline-environments-generic/; https://olake.io/docs/install/olake-ui/offline-environments-aws/; https://olake.io/docs/install/kubernetes/]
- [high] *docs-gap-10-k8s-storage*: Recurring problem: Kubernetes needs a ReadWriteMany StorageClass (olake#924, olake-helm#113). S3 log-file storage mode now removes that need. It requires OLake 0.12.0, UI 0.7.0, chart 0.0.30 and worker 0.4.0, and the docs answer that. They do not cover the image-availability pitfall: the worker v0.4.0 image appeared on Docker Hub only on 2026-10-15 (olake-helm#231). [evidence: https://olake.io/docs/install/kubernetes/; https://github.com/datazip-inc/olake-helm/issues/231; measured: Docker Hub tags API for olakego/ui-worker (v0.4.0 last_updated 2026-10-15T06:11:50)]
- [high] *docs-gap-11-job-control*: Recurring problem: job control.
- A running sync on Kubernetes cannot be cancelled from the UI (olake#955).
- Clear Destination gets stuck 'InProgress' (#877).
- Containers are orphaned when a Temporal worker dies (olake-ui#93).
The docs partly answer it: Cancel and Clear Destination semantics are explained, but there is no troubleshooting for stuck jobs. [evidence: https://github.com/datazip-inc/olake/issues/955; https://github.com/datazip-inc/olake/issues/877; https://olake.io/docs/getting-started/job-level-properties/]
- [high] *docs-gap-12-large-sources*: Recurring problem: on large sources, discovery and job create/update fail with a misleading timeout (olake-ui#434, open), and saving a draft fails silently with a large catalog (olake-ui#446, open). The docs partly answer it with the CLI --timeout and --max-discover-threads flags and the UI 'Max Parallel Threads for Discovery' setting. v0.11.0 added progressive discovery that returns partial schemas. The UI timeout error itself is undocumented. [evidence: https://github.com/datazip-inc/olake-ui/issues/434; https://olake.io/docs/install/docker-cli/; https://olake.io/docs/getting-started/job-level-properties/; https://olake.io/docs/release/ingestion/v0.11.0/]
- [high] *docs-gap-13-kafka*: Recurring problem: Kafka source pitfalls.
- One rebalance halts all readers (olake#1241) and a graceful exit commits unread offsets (#1240), both closed.
- Avro or Protobuf messages are mis-decoded as JSON without a schema registry (#1239).
- tls_skip_verify is ignored without an ssl block (#1243, open).
- Consumer-group corruption.
The docs partly answer it: they cover the dedicated group per job, graceful shutdown on rebalance, the Avro registry requirement, the retention warning, and corruption recovery (UI: new job; CLI: change consumer_group_id). Protobuf and the TLS flags are not covered. [evidence: https://olake.io/docs/connectors/kafka/; measured: gh api issues listing (olake#1239-#1243); https://kafka.apache.org/43/operations/basic-kafka-operations/]
- [high] *docs-gap-14-mongodb*: Recurring problem: MongoDB.
- TLS CA and cert files cannot be passed to the connector container (olake#1080); docs PR #475 for inline TLS certs is open.
- Cosmos DB is unsupported (#1272, open).
- Backfill fails with the timestamp strategy (#1262, open; PR #1295).
- Type conversion fails on large collections (#409).
The docs do not answer these. Troubleshooting covers only connection failures, replica-set CDC, missing files and filename length. [evidence: https://olake.io/docs/connectors/mongodb/; measured: gh api issues listing; gh pr list -R datazip-inc/olake-docs (PR #475 open)]
- [high] *docs-gap-15-fusion-ops*: Recurring problem: Fusion operations.
- Tables stuck in PLANNING (olake-fusion#11).
- Automatic snapshot expiry, now disabled in v0.1.x.
- Not all partitions planned in one run (#29).
- No 'Run now' option (#30).
- Metrics exporter broken (#23).
The docs only partly answer this, through release notes. There is no Fusion troubleshooting page, and the Fusion architecture, terminology and query-engine pages are empty or 'Coming soon'. [evidence: https://olake.io/docs/fusion/release/maintenance/v0.1.0/; https://olake.io/docs/fusion/core/architecture/; https://olake.io/docs/fusion/core/terminologies/; https://olake.io/docs/fusion/core/compatibility/query-engines/; https://github.com/datazip-inc/olake-fusion/releases/tag/v0.1.4]
- [high] *stale-misleading-pages*: Some live sitemap pages (all returning 200) are stale or misleading:
- /docs/connectors/kafka/overview/ says 'Kafka Source Coming Soon / Work in Progress', although Kafka has been supported since v0.3.0.
- /docs/connectors/overview/ (lastmod 2025-06-23) lists Kafka as WIP and S3 as 'check issue', and has no MSSQL or DB2.
- /docs/tutorials/enable-oplogs/ says 'Coming Soon'.
- /docs/archive/kubernetes/ describes an archived CronJob method that needs RWX storage.
- /docs/core/configs/{catalog,state}/ are 'moved' stubs.
- /docs/core/architecture/ only points to a blog post.
- /docs/writers/iceberg/gcp/ says 'more details soon'.
In total, 18 pages have less than 1,300 chars of article text. Exclude or demote these in the index. [evidence: https://olake.io/docs/connectors/kafka/overview/; https://olake.io/docs/connectors/overview/; https://olake.io/docs/tutorials/enable-oplogs/; https://olake.io/docs/archive/kubernetes/; https://olake.io/docs/core/architecture/; https://olake.io/docs/writers/iceberg/gcp/; measured: extracted <article> text per page; 18/124 pages <1300 chars]
- [high] *first-party-contradictions*: First-party sources contradict each other:
1. Fusion default schedule: configure-first-compaction says Lite 1h / Medium 8h / Full never; compaction/configuration says 24h each; the /olake-fusion/ FAQ JSON-LD says Lite 20m / Medium 40m in the benchmark.
2. The Postgres troubleshooting page suggests ssl.mode 'allow', which is not among the documented modes (olake-docs#526, open).
3. The source.json page mentions Oracle 'LogMiner setup', but there is no Oracle CDC.
4. The overview table puts Kafka under 'CDC Only'; the README calls it 'Bounded Incremental'.
5. The MySQL page lists binlog_row_metadata=FULL as required; the v0.10.0 notes say CDC works without it.
6. The schema page says discovery runs at the start of every sync (last substantive edit 2026-06-14); since v0.10.0 sync skips discovery unless --discover-schema is passed (docs PR #501 is still open).
7. The schema page calls DATE→TIMESTAMP an 'Iceberg v2' promotion; the Iceberg spec allows it only in v3+.
8. The olake README quickstart uses the legacy docker-compose.yml (with Elasticsearch); the docs use docker-compose-v1.yml, which replaced it after 2026-01-30.
9. The README roadmap lists Interoperability and Iceberg v3 as 'coming soon'; both shipped in v0.11.0.
10. The blog post at /blog/creating-job-olake-docker-cli/ runs sync with --config streams.json --catalog catalog.json, which conflicts with the docs' --config source.json --streams streams.json. [evidence: https://olake.io/docs/fusion/getting-started/configure-first-compaction/; https://olake.io/docs/fusion/compaction/configuration/; https://olake.io/olake-fusion/; https://olake.io/docs/connectors/postgres/; https://olake.io/docs/core/configs/source/; https://olake.io/docs/connectors/mysql/; https://olake.io/docs/release/ingestion/v0.10.0/; https://olake.io/docs/features/schema/; https://olake.io/docs/install/docker-cli/; https://iceberg.apache.org/spec/; https://github.com/datazip-inc/olake; https://github.com/datazip-inc/olake-ui; https://olake.io/blog/creating-job-olake-docker-cli/; https://raw.githubusercontent.com/datazip-inc/olake-docs/master/blog/2025-09-04-creating-job-olake-docker-cli.mdx]
- [high] *missing-topics*: Topics with no docs coverage:
- Fusion snapshot expiration, orphan-file and metadata cleanup. The only mention is 'Disabled automatic snapshot expiry' in the v0.1.x notes.
- Whether Fusion supports Iceberg v3 or deletion vectors. Fusion's pom pins Iceberg 1.7.2; OLake's writer uses 1.10.2 and writes DVs since v0.11.0.
- How Fusion should interact with S3 Tables' built-in maintenance. AWS says S3 Tables maintenance goes through S3 Tables APIs.
- A consolidated cross-component version matrix.
- A published FAQ: docs/drafts/faqs.mdx is a draft and /docs/faq*/ returns 404. Only the product-page FAQs exist, at /olake-go/ and /olake-fusion/.
- SSO/OIDC (olake-ui#383).
- Windows PowerShell setup (olake-docs#357).
- MySQL replica-mode CDC (olake-docs#10). [evidence: https://olake.io/docs/fusion/release/maintenance/v0.1.0/; https://raw.githubusercontent.com/datazip-inc/olake-fusion/master/pom.xml; https://raw.githubusercontent.com/datazip-inc/olake/master/destination/iceberg/olake-iceberg-java-writer/pom.xml; https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html; https://olake.io/olake-go/; https://olake.io/olake-fusion/; measured: curl https://olake.io/docs/faq/ -> 404; grep of 124 extracted pages for 'deletion vector|v3' in fusion pages -> none]
- [medium] *community-signal*: The community is on an invite-only Slack (workspace getolake). Web search found no public archive.
- GitHub Discussions on olake has 7 threads in total, only 1 of them Q&A.
- Issues, excluding PRs: olake 321, olake-ui 87, olake-helm 24, olake-fusion 9, olake-docs 29.
- Excluding todo and good-first/second issues, 200 were filed by the community: olake 119, olake-ui 37, olake-helm 16, olake-fusion 1, olake-docs 27.
- Rough title themes (overlapping): jobs/UI/state 25, types/schema/timestamps 23, Postgres WAL/LSN/TOAST 20, deployment 20, MySQL/MariaDB 16, catalogs 13, MongoDB 9, Kafka 5, upsert/dedup 5, MSSQL 4, S3 2, Oracle/DB2 2. [evidence: https://olake.io/docs/community/channels/; https://olake.io/slack/; measured: gh api graphql discussions totalCount=7; measured: gh api --paginate repos/datazip-inc/<repo>/issues?state=all; keyword regex classification of titles]
- [high] *outside-sources-iceberg-amoro*: Iceberg and Amoro outside sources:
- Iceberg maintenance (latest is 1.12.0): expire snapshots, remove old metadata (write.metadata.previous-versions-max default 100, delete-after-commit default false) and delete orphan files (default retention 3 days; a short retention can corrupt tables). Use it for 'does Fusion do X' and storage-growth questions, with an outside-source label. Medium risk.
- Iceberg Spark procedures: rewrite_data_files, expire_snapshots (older_than default 5 days, retain_last 1), remove_orphan_files (3 days), rewrite_position_delete_files, rewrite_manifests.
- Iceberg spec: v2 deletes, v3 deletion vectors (Puffin, at most one DV per data file, position deletes deprecated in v3), and type-promotion rules. It is a living spec that already includes v4 draft text. It wins on format semantics; OLake docs win on what OLake writes.
- Amoro self-optimizing and configurations: minor/major/full optimizing maps to Lite/Medium/Full, and fragments are files under target-size ÷ fragment-ratio. HIGH risk: Amoro's target-size default is 128MB vs Fusion's 512MB, and Amoro's table-expire.enabled defaults to true (snapshot.keep.duration 12h) while Fusion v0.1.4 disabled automatic expiry. These are dev docs. Use them for concepts only, labeled 'upstream'. [evidence: https://iceberg.apache.org/docs/latest/maintenance/; https://iceberg.apache.org/docs/latest/spark-procedures/; https://iceberg.apache.org/spec/; https://amoro.apache.org/docs/latest/self-optimizing/; https://amoro.apache.org/docs/latest/configurations/]
- [high] *outside-sources-databases*: Database outside sources:
- PG replication config (PG18): wal_sender_timeout 60s (0 disables), max_slot_wal_keep_size −1, max_replication_slots and max_wal_senders 10, idle_replication_slot_timeout 0. Low risk.
- PG logical decoding concepts: slots keep WAL even with no consumer, one receiver per slot at a time, decoding on a standby needs hot_standby_feedback. This explains OLake's 'unique slot per job' rule.
- PG ALTER TABLE for REPLICA IDENTITY.
- MySQL 8.4 binlog options: binlog_format ROW (deprecated variable), binlog_row_image full, binlog_row_metadata MINIMAL by default, binlog_expire_logs_seconds 30 days. Medium risk against OLake's FULL requirement. curl got 403 from bot protection; WebFetch worked.
- MongoDB oplog: 5% of disk, clamped to 990MB–50GB; replSetResizeOplog; oplogMinRetentionHours; a consumer that falls outside the window must resync.
- MongoDB change streams: need a replica set or sharded cluster (not standalone) and WiredTiger; resume tokens must still be in the oplog.
- SQL Server CDC: retention 4320 min (3 days), at most 2 capture instances per table, SQL Server Agent required, DDL needs a new capture instance. Low risk; it agrees with OLake.
Rule for all of these: OLake docs decide what OLake requires; vendor docs explain defaults and how to set them, with an 'outside OLake docs' label. [evidence: https://www.postgresql.org/docs/current/runtime-config-replication.html; https://www.postgresql.org/docs/current/logicaldecoding-explanation.html; https://www.postgresql.org/docs/current/sql-altertable.html; https://dev.mysql.com/doc/refman/8.4/en/replication-options-binary-log.html; https://www.mongodb.com/docs/manual/core/replica-set-oplog/; https://www.mongodb.com/docs/manual/changeStreams/; https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/about-change-data-capture-sql-server]
- [high] *outside-sources-kafka-catalogs*: Kafka and catalog outside sources:
- Kafka 4.3 consumer configs: group.id; auto.offset.reset default latest; session.timeout.ms 45s; max.poll.interval.ms 5min. kafka.apache.org/documentation/ is a JS redirect, so cite the versioned /43/ URLs.
- Kafka basic operations: kafka-consumer-groups.sh --describe, --reset-offsets (the group must be inactive), --delete. Medium risk: resetting OLake's offsets can duplicate or skip data, so OLake's fix (a new consumer group) comes first.
- S3 Tables REST endpoint: https://s3tables.<region>.amazonaws.com/iceberg; the warehouse is the table-bucket ARN; SigV4 signing name s3tables; single-level namespaces; no OAuth; 50MB metadata.json limit; maintenance via S3 Tables APIs.
- Databricks Unity Iceberg REST: endpoint /api/2.1/unity-catalog/iceberg-rest; external writes only to managed Iceberg tables; EXTERNAL USE SCHEMA privilege; PAT or OAuth; credential vending.
- Athena Iceberg: v2 only, Glue catalog only, millisecond timestamps.
- Lakekeeper (Rust, OpenFGA), Polaris (1.8.0 listed) and Nessie (0.109.0 listed) home pages. BigLake REST and Snowflake Horizon external-engine pages (status 200, titles checked).
- Temporal docs for orchestration concepts.
Rule: the OLake REST-catalog tab comes first; vendor docs cover privileges, endpoints and limits. [evidence: https://kafka.apache.org/43/configuration/consumer-configs/; https://kafka.apache.org/43/operations/basic-kafka-operations/; https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html; https://docs.databricks.com/aws/en/external-access/iceberg; https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html; https://docs.lakekeeper.io/; https://polaris.apache.org/; https://projectnessie.org/; https://cloud.google.com/bigquery/docs/blms-rest-catalog; https://docs.snowflake.com/en/user-guide/tables-iceberg-query-using-external-query-engine-snowflake-horizon; https://docs.temporal.io/]
- [medium] *precedence-rule*: Proposed global precedence when sources disagree:
1. The current OLake docs page. Prefer the more specific page, and the one with the newer olake-docs git commit, and say explicitly that the pages disagree.
2. GitHub release notes for datazip-inc repos, for anything newer than the docs; always state the version and date.
3. READMEs, the product-page FAQs and the first-party blog, only when the docs are silent, with their date. The README roadmap and 2024–25 blog posts are known stale.
4. Upstream vendor docs, only for how that external system behaves, labeled 'outside OLake docs'. Never use them for OLake defaults, keys or version support.
5. Amoro, for concepts only, labeled 'upstream; Fusion may differ'.
6. GitHub issues only as 'known issue #N (open/closed)', never as facts. [evidence: https://olake.io/docs/; https://github.com/datazip-inc/olake/releases; https://amoro.apache.org/docs/latest/configurations/; https://olake.io/docs/fusion/release/maintenance/v0.1.0/]
- [high] *freshness-cadence*: Freshness cadence.
- olake-docs: 25 commits touched docs/ in the last 30 days and 44 in the last 60. Counting the whole repo gives 101 and 157.
- Monthly docs/ commits from 2025-10 to 2026-10 (partial): 30, 17, 18, 23, 37, 13, 16, 13, 37, 26, 47, 26, 8.
- Releases in the last 30/60 days: olake 6/11, olake-ui 5/7, olake-helm 3/5, olake-fusion 0/1.
- Most volatile pages over 60 days, excluding the site rebuild: writers/iceberg/catalog/rest.mdx 16 commits; terminologies/olake 6; install/olake-ui, install/kubernetes and install/docker-cli 5 each; terminologies/general and creating-first-pipeline 4 each; JDBC and Hive catalogs, compatibility-engines, job-level-properties, playground, Fusion k8s, the S3, MySQL and Kafka connectors, commands-and-flags and the v0.11.0 notes 3 each.
- All 8 connector pages changed on 2026-10-16 (PR #580). [evidence: measured: git log --since on blobless sparse clone of datazip-inc/olake-docs (docs/), excluding commit bc3013d for per-file counts; measured: gh api repos/datazip-inc/<repo>/releases published_at]
- [high] *freshness-lastmod-unreliable*: Sitemap lastmod is unreliable. A site rebuild on 2026-10-06 (commit bc3013d, 'Rebuild the site on a shared design system') touched 213 docs files, which is why lastmod clusters on 10-06. All 85 dated blog posts show lastmod 2026-10 although the posts date from 2024-09 to 2026-10. Use olake-docs git commit dates and the GitHub releases API instead. GitHub Pages serves the docs with cache-control max-age=600, so re-crawls see deploys within about 10 minutes. https://olake.io/llms.txt exists (22.6KB, a curated link list); llms-full.txt returns 404. [evidence: https://olake.io/sitemap.xml; https://olake.io/llms.txt; measured: git show --stat bc3013d -- docs -> 213 files changed; measured: curl -I https://olake.io/docs/ -> server GitHub.com, cache-control max-age=600]
- [high] *freshness-pending-changes*: Changes likely to land around the event, which would make answers stale:
- streams v2 (olake PR #1145, open, updated 10-14) splits the catalog into available_streams.json and selected_streams.json with new flags --available-streams and --selected-streams. --streams and --catalog become deprecated. Docs PR #558 has the migration guide.
- Other open staging PRs updated 10-16: Azure ADLS storage for Iceberg catalogs (#1273), Azure Blob for Parquet (#1247), MySQL CDC across switchovers (#1283), MySQL binary columns (#1137), Postgres TOAST resolution (#1264), narrowing delete formats by catalog (#1290), a SeaweedFS REST catalog (#1281), and non-retryable exit codes (#1252, #1284).
- olake-docs PR #579 updates the Fusion optimizer configs.
- olakego/fusion:test-next-release was pushed 10-13.
Re-crawl and re-index on the morning of 2026-10-18. [evidence: measured: gh pr view 1145 -R datazip-inc/olake; gh pr list -R datazip-inc/olake --state open; gh pr list -R datazip-inc/olake-docs --state open; measured: Docker Hub tags API olakego/fusion]
- [high] *stale-answer-patterns*: What a stale answer looks like for this product:
- Saying Kafka is 'coming soon', or that Kafka has no upsert (it has since v0.12.1).
- Recommending wal2json instead of pgoutput.
- Giving the legacy docker-compose.yml (with Elasticsearch) instead of docker-compose-v1.yml.
- Requiring NFS/RWX volumes instead of S3 log storage.
- Saying Unity is append-only (that limitation was removed 2026-09-23).
- Offering only equality deletes (positional came in v0.10.0 and DVs in v0.11.0).
- Treating Interoperability and Iceberg v3 as future roadmap items.
- Stating catalog-name character rules that predate v0.12.1.
- Using the CLI --catalog flag from 2025 blogs.
- Soon: describing streams.json without mentioning the v2 split.
- Answering 'latest version' from an old index. GitHub has v0.12.1; the docs notes stop at v0.12.0. [evidence: https://olake.io/docs/connectors/kafka/overview/; https://olake.io/docs/connectors/postgres/; https://olake.io/docs/getting-started/quickstart/; https://olake.io/docs/install/kubernetes/; https://olake.io/docs/release/ingestion/v0.10.0/; https://olake.io/docs/release/ingestion/v0.11.0/; measured: olake-docs git log (commit eeb442d 'remove append only limitation from unity', 2026-09-23)]
- [high] *retrieval-poc*: Feasibility POC. I extracted <article> text from all 124 pages; Docusaurus server-renders every tab panel (37 pages have tabs, 202 panels, 122 hidden by default). I split it into 1,193 H2/H3 chunks and ran a pure-Python BM25 on 36 seed questions (35 answerable).

| Variant | hit@1 | hit@3 | hit@5 |
|---|---|---|---|
| Page-level | 18/35 | 26/35 | 29/35 |
| Chunk-level | 22/35 | 26/35 | 30/35 |
| Chunk + 3 rules | 27/35 | 28/35 | 32/35 |

The three rules: demote release notes older than v0.11 to 0.3×, boost the connector page 1.6× when its source is named, and a synonym map (CDC Only↔strict_cdc, MariaDB→MySQL, latest→release).

The remaining misses:
- Negative questions ('Oracle CDC?'): the Oracle page never mentions CDC, so old release notes win.
- Overview and comparison questions.
- The Snowflake/equality-delete question, because those terms appear everywhere.
- The unanswerable pricing/SLA question retrieved unrelated pages, so the answerer needs a score threshold and an 'I don't know' path.
The scripts are in the scratchpad. [evidence: measured: python3 -I scripts/bm25_poc.py data/text data/eval_seed.json page|chunk; scripts/bm25_rules.py (scratchpad/wf/olake-domain); measured: tab panel count via regex over <article> HTML of 124 pages]
- [high] *citation-hygiene*: Citation hygiene:
- Old doc URLs return HTTP 200 with a meta-refresh and a canonical link to the new page, for example /docs/connectors/postgres/overview → /docs/connectors/postgres/, /docs/benchmarks/compaction/ → /docs/fusion/getting-started/compaction/, and /docs/playground/olake-iceberg-presto/ → /docs/getting-started/playground/.
- Real misses return status 404 with the title 'Page Not Found | OLake'.
- So validate citations against the sitemap and canonicalize meta-refresh stubs.
- The README still links several of these redirect URLs.
- Deep-link REST catalog answers with ?rest-catalog=<tab>; the docs use these query params internally. [evidence: https://olake.io/docs/connectors/postgres/overview/; https://olake.io/docs/benchmarks/compaction/; https://olake.io/docs/understanding/compatibility-catalogs/; measured: curl -L status + <meta http-equiv=refresh> parse; curl https://olake.io/docs/this-page-does-not-exist-xyz/ -> title 'Page Not Found | OLake']
- [medium] *eval-seed*: 36 seed eval questions with gold pages (stored in data/eval_seed.json):
- Q01 Postgres sync modes. Gold: connectors/postgres.
- Q02 Oracle CDC. Expected: No.
- Q03 DB2 CDC. Expected: No.
- Q04 MySQL CDC settings.
- Q05 'LSN not updated' fix.
- Q06 deletes keep only the PK. Expected: REPLICA IDENTITY FULL.
- Q07 sharing a replication slot. Expected: No.
- Q08 FR+CDC vs CDC Only.
- Q09 _olake_id with no PK.
- Q10 delete formats and v3.
- Q11 Snowflake reading equality deletes. Expected: No.
- Q12 catalog list.
- Q13 Horizon version. Expected: v0.11.0.
- Q14 CLI sync with --state.
- Q15 clear-destination.
- Q16 Kafka upsert. Expected: Go 0.12.1 / UI 0.7.1.
- Q17 Kafka consumer-group corruption.
- Q18 Lite/Medium/Full.
- Q19 Fusion default schedules. Expected: must cite the conflicting pages.
- Q20 snapshot expiry or orphan cleanup in Fusion. Expected: not documented; automatic expiry disabled.
- Q21 Helm install.
- Q22 default login. Expected: admin/password; change via x-signup-defaults.
- Q23 Fusion via compose (ENABLE_OPTIMIZATION=true --profile fusion).
- Q24 partition transforms.
- Q25 INT→BIGINT.
- Q26 MongoDB CDC prerequisites.
- Q27 MariaDB. Expected: Yes.
- Q28 MSSQL 3-day retention and 2017+.
- Q29 DynamoDB or BigQuery source. Expected: not supported.
- Q30 latest release. Expected: v0.12.1, with a freshness caveat.
- Q31 Prometheus.
- Q32 air-gapped install.
- Q33 Go vs Fusion.
- Q34 engines that read DVs.
- Q35 S3 Tables setup.
- Q36 pricing or SLA. Expected: not documented; point to hello@olake.io or /contact/. [evidence: https://olake.io/olake-go/; measured: data/eval_seed.json written in scratchpad; gold URLs are the docs pages listed in the support/glossary findings]
- [high] *product-page-faqs*: Two first-party FAQ sources sit outside /docs/ and are in the sitemap, as FAQPage JSON-LD:
- https://olake.io/olake-go/ covers enterprise plans (contact hello@olake.io), licensing (Apache 2.0) and integrations.
- https://olake.io/olake-fusion/ covers standalone use without OLake Go (yes, through the catalog), whether to pause ingestion during compaction (no), how often compaction runs (benchmark values of 20m/40m), licensing cost (open source; you pay only for compute), and configuration (target-size only; 512MB in the benchmark).
Index both pages; they answer common pre-sales questions. [evidence: https://olake.io/olake-go/; https://olake.io/olake-fusion/; https://raw.githubusercontent.com/datazip-inc/olake-docs/master/src/data/landing/go/faq.ts]

## Open questions
- Does a UI-scheduled sync still run schema discovery every time? features/schema says yes; since v0.10.0 sync skips discovery unless --discover-schema is passed, and the worker may run discover separately.
- Can OLake Fusion compact Iceberg v3 tables that use deletion vectors? Fusion's pom pins Iceberg 1.7.2 and its docs never mention DVs; OLake Go has written DVs since v0.11.0.
- Which Fusion default schedule is authoritative: Lite 1h / Medium 8h / Full never, or 24h for each type? The product FAQ's 20m/40m values describe the benchmark setup.
- Is binlog_row_metadata=FULL still required for MySQL CDC after v0.10.0's 'CDC without full binlog metadata'?
- After v0.12.1 (#1184, 'allow numbers in iceberg catalog names'), is the REST page's 'lowercase letters and underscores only' rule stale for every catalog type?
- Will streams v2 (olake PR #1145), Azure ADLS for Iceberg (#1273) or MySQL switchover CDC (#1283) merge before 2026-10-18? Any of them would change correct answers.
- Which version baseline and what mix of ingestion vs Fusion questions will the hidden test set use? Do GitHub release notes and issues count as acceptable citation sources?
- Is there any public Slack archive? Web search found none, and Discussions has only 7 threads.
- Is Fusion supported standalone without OLake Go? The product FAQ says yes via the catalog, but olake-fusion#5 asks for a standalone service, so the deployment story is unclear.
- Which LLM provider supplies the event's credits? This affects context budget: the full docs are about 262K tokens, so RAG is needed for smaller-context models.

## Report path note
NOT WRITTEN. The harness blocked report .md files from this subagent, so the full report content is in this structured return. Small notes and scripts are kept under (probe script in a deleted scratch dir): scripts/ (sitemap.py, extract.py, bm25_poc.py, bm25_rules.py, issue_themes.py, tabs.py, html2text.py) and data/ (eval_seed.json, sitemap.xml, llms.txt, READMEs, release and issue JSON, docs-last-substantive-current.txt). Clones and large downloads were deleted.
