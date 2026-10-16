Research agent output, 2026-10-16; evidence for docs/research.md

# eval-ingestion

## summary
Ingestion eval set for "Ask OLake" (event on 2026-10-18), built on 2026-10-16.

**No report.md was written.** The harness refused to let a subagent write a report .md ("Subagents should return findings as text"), so the full report is in this return (summary + coverage_notes). The machine-readable set, including 152 evidence quotes, is in notes/questions.json.

**Shape of the set**
- 40 questions: SET 7, SRC 14, SYNC 11, DST 8.
- 36 answerable and 4 negative, one per category: SET-07 Quartz cron, SRC-08 Oracle CDC/LogMiner, SYNC-05 INTEGER→TEXT type change, DST-06 CSV/JSON output.
- Difficulty is 20 easy, 14 medium, 6 hard (exactly 50/35/15%).
- SRC covers all 8 sources.
- 6 questions cite repo files:

| ID | Repo file(s) |
|---|---|
| SET-06 | olake-ui docker-compose-v1.yml and README.md |
| SRC-08 | olake drivers/oracle/internal/cdc.go |
| SRC-13 | olake drivers/kafka/README.md and resources/spec.json |
| SYNC-02 | olake drivers/abstract/cdc.go |
| SYNC-08 | olake drivers/abstract/abstract.go and constants/constants.go |
| SYNC-11 | olake drivers/mysql/internal/mysql.go |

- Four of these cannot be answered correctly from the docs alone: SET-06, SRC-13, SYNC-08, SYNC-11.
- All 40 are verified=true.

**Method and measurements**
- **Docs:** fetched all 124 /docs/ URLs from https://olake.io/sitemap.xml with curl (124 × HTTP 200). Converted each `<article>` with a stdlib HTMLParser script. Read about 55 ingestion pages, fully or in the relevant sections.
- **Repos:**
  - datazip-inc/olake: depth-1 clone, HEAD d20c68e (2026-10-15T18:47+05:30).
  - datazip-inc/olake-ui: sparse clone, HEAD 56826cf (2026-10-15T18:57+05:30), plus docker-compose-v1.yml and README.md from raw.githubusercontent.com.
  - Every GitHub blob URL used as a source returns HTTP 200.
- **Latest releases (gh api):** OLake v0.12.1 at 2026-10-15T13:27:40Z (https://github.com/datazip-inc/olake/releases/tag/v0.12.1); OLake UI v0.7.1 at 2026-10-15T13:27:48Z.
- **validate.py:** checks canonical sitemap URLs, no #anchors, 1-3 sources, 2-4 must_mention, category quotas, 4 negatives and SRC coverage. All 152 evidence quotes were found in the fetched source text. A self-test confirmed it flags a broken quote and a non-canonical URL.
- **BM25 probe** (stdlib; 1,039 chunks of 200 words over 124 pages):
  - The best expected page is at rank 1 for 31 of 40, top 3 for 36, top 5 for 38.
  - Misses: SET-04 (rank 12) and SRC-10 (rank 30).
  - Second sources often sit deep: SET-04's job-level page at 69, DST-06's /docs/ at 34, SYNC-02's terminologies page at 17, SRC-05's v0.10.0 notes at 12.
  - So lookup is mostly easy. What makes questions hard is multi-hop retrieval, version drift and repo-only facts.
- **score.py** (heuristic scorer for the runbook), checked on mock answers:
  - Perfect answers: citation 1.00, must_mention 1.00, negatives 4/4.
  - "I don't know": 0 and 0.
  - A single wrong page: 0.03 and 0.00.
- **Freshness:** every cited docs page was last updated between Oct 6 and Oct 15, 2026; all 8 connector pages on Oct 15. Re-crawl before the 14:30 code freeze.

**Traps and doc drift the bot must handle** (all opened 2026-10-16)
1. **MySQL initial_wait_time:** the docs example uses 10 (https://olake.io/docs/connectors/mysql/), but the driver enforces a 120 s minimum (https://github.com/datazip-inc/olake/blob/master/drivers/mysql/internal/mysql.go). The Postgres driver instead uses 10800 when the value is below 120.
2. **binlog_row_metadata=FULL:** listed as a prerequisite, but optional since v0.10.0 (https://olake.io/docs/release/ingestion/v0.10.0/).
3. **Kafka security protocols:** the docs list 3; the driver README and spec.json add SSL (https://github.com/datazip-inc/olake/blob/master/drivers/kafka/README.md).
4. **Kafka upsert:** needs OLake 0.12.1, but the docs release notes stop at v0.12.0 (https://olake.io/docs/release/ingestion/v0.12.0/).
5. **Catalog names:** the docs say lowercase letters and underscores only (https://olake.io/docs/writers/iceberg/catalog/jdbc/), but the v0.12.1 notes say numbers are now allowed.
6. **Schema discovery:** the schema page says discovery runs at the start of every sync (https://olake.io/docs/features/schema/). The CLI sync skips discovery unless --discover-schema is passed (https://olake.io/docs/install/docker-cli/).
7. **Stale pages:**
   - /docs/connectors/overview/ (last updated Jun 23, 2025): Kafka "WIP", S3 "check issue", no MSSQL or DB2.
   - /docs/connectors/kafka/overview/ and /docs/tutorials/enable-oplogs/ just say "Coming Soon".
   - /docs/core/configs/source/ mentions an Oracle "LogMiner setup", but Oracle has no CDC.
   - /docs/writers/iceberg/gcp/ says GCS Iceberg works only through the Hive catalog, but BigLake support exists (v0.9.0).
8. **Conflicting requirements:**
   - RAM: 4 GB (https://olake.io/docs/getting-started/quickstart/) vs a minimum of 8 vCPU/16 GB (https://olake.io/docs/install/olake-ui/).
   - Java: 17+ (https://olake.io/docs/writers/iceberg/troubleshooting-local/) vs 21 (https://olake.io/docs/community/setting-up-a-dev-env/).
9. **Azure Postgres fix:** the docs say set ssl.mode "allow" (https://olake.io/docs/connectors/postgres/), which is not one of the documented SSL modes.
10. **Naming and defaults:** "CDC Only" (terminologies), strict_cdc (streams.json) and "Strict CDC" (job-level page) are the same mode. The docs say only Kafka defaults to Append; the code also makes S3 append-by-default (constants.go).
11. **Near-duplicate pages:** /docs/getting-started/olake-ui/ and /docs/getting-started/quickstart/.
12. **olake README quickstart** still uses the legacy docker-compose.yml.

**Runbook recommendations**
- Index the docs plus a small repo allowlist: driver READMEs, resources/spec.json, constants.go, and olake-ui's compose file and README.
- Emit citations in canonical sitemap form (trailing slash, no anchors).
- Use hybrid BM25 + dense retrieval.
- When docs and code disagree, give both and name the version.
- For negatives, say "not supported" plus the support list, not "I don't know".
- Use an LLM judge on must_mention, with score.py as a smoke test.

**Open questions for the lead**
1. Will graders accept repo-derived answers that contradict the docs (SYNC-11, SRC-13)?
2. Do citations to near-duplicate pages count?
3. The provider of the event's LLM credits isn't named, so the judge model is still open.
4. Blog pages (86 URLs) and Fusion are not covered here.

## coverage_notes
**Topic coverage by category**

- **SET:**
  - SET-01: UI quickstart and default credentials
  - SET-02: custom admin credentials (x-signup-defaults)
  - SET-03: CLI discover via Docker
  - SET-04: discover timeout and thread count
  - SET-05: Helm install on EKS
  - SET-06: Temporal UI under the debug compose profile (repo)
  - SET-07: Quartz cron (negative)
- **SRC:**
  - SRC-01: RDS Postgres parameter group
  - SRC-02: Postgres "LSN not updated" error
  - SRC-03: Supabase direct connection and IPv6
  - SRC-04: MySQL CDC prerequisites
  - SRC-05: binlog_row_metadata optional since v0.10.0
  - SRC-06: MongoDB replica set and user roles
  - SRC-07: Oracle FLASHBACK / DBMS_FLASHBACK grants
  - SRC-08: Oracle CDC (negative)
  - SRC-09: enabling CDC on MSSQL on RDS
  - SRC-10: MSSQL capture instance after DDL
  - SRC-11: DB2 on arm64
  - SRC-12: Kafka Avro with schema registry
  - SRC-13: Kafka TLS-only SSL protocol (repo)
  - SRC-14: S3 folder-to-stream mapping and IAM
- **SYNC:**
  - SYNC-01: incremental vs CDC, and deletes
  - SYNC-02: strict_cdc (repo)
  - SYNC-03: state.json contents per source
  - SYNC-04: cancel and resume
  - SYNC-05: INTEGER→TEXT type change (negative)
  - SYNC-06: new column and backfill
  - SYNC-07: Kafka upsert and dedup_keys
  - SYNC-08: normalization defaults per source (repo)
  - SYNC-09: Postgres numeric→float mapping
  - SYNC-10: MySQL chunk-split error and ANALYZE TABLE
  - SYNC-11: MySQL initial_wait_time minimum of 120 s (repo)
- **DST:**
  - DST-01: Glue destination.json
  - DST-02: MinIO with a JDBC catalog (path style, SSL)
  - DST-03: Parquet to GCS with HMAC keys
  - DST-04: Azure ADLS Gen2 via Lakekeeper
  - DST-05: Iceberg partition transforms
  - DST-06: CSV/JSON output (negative)
  - DST-07: Athena and delete formats
  - DST-08: Helm index PVC for positional deletes
  - Storage targets covered: S3/Glue, MinIO, GCS and Azure. The local Parquet writer is not tested directly.

**Not covered**
- Out of scope: Fusion, and the blog, webinar, compare and customer-story pages.
- Not chosen for this set: alerts, Prometheus metrics, the UI API, benchmarks, playground, the data filter, Clear Destination, Parquet partition_regex, and the Polaris, Nessie, Unity, S3 Tables, BigLake and Horizon catalog specifics.

**Reserve items** (all opened 2026-10-16; use them to rotate or expand the set)

Reserve negatives:
- **Kafka SCRAM-SHA-256:** not supported; only PLAIN and SCRAM-SHA-512 (https://olake.io/docs/connectors/kafka/). The driver's kafka.go rejects other mechanisms.
- **DB2 CDC:** only Full Refresh and Full Refresh + Incremental (https://olake.io/docs/connectors/db2/). The driver returns "CDC is not supported for DB2".
- **S3 source Avro or ORC files:** only CSV, JSON, XML and Parquet (https://olake.io/docs/connectors/s3/).
- **MSSQL verify-ca or verify-full SSL:** only require and disable are listed (https://olake.io/docs/connectors/mssql/).
- **Unity external tables:** managed tables only (https://olake.io/docs/writers/iceberg/catalog/rest/).
- **Slack and Teams alerts at once:** one webhook per system (https://olake.io/docs/getting-started/alerts-and-notifications/).
- **/metrics on CLI deployments:** available in the OLake UI only (https://olake.io/docs/monitoring-and-observability/metrics/).

Reserve answerables:
- **Postgres** (https://olake.io/docs/connectors/postgres/):
  - Deleted rows keep only the primary key, and TOAST columns come back null; the fix is REPLICA IDENTITY FULL.
  - Row-level security yields zero rows; the fix is BYPASSRLS.
  - Azure "no pg_hba.conf entry … no encryption" error; the docs say set ssl.mode to "allow" (an undocumented mode).
- **Postgres setup pages:**
  - publish_via_partition_root for partitioned tables (https://olake.io/docs/connectors/postgres/setup/generic/)
  - Cloud SQL: cloudsql.logical_decoding=on (https://olake.io/docs/connectors/postgres/setup/gcp/)
- **MySQL:**
  - IST timezone warning: set jdbc_url_params.time_zone (https://olake.io/docs/connectors/mysql/)
  - RDS binlog retention via mysql.rds_set_configuration (https://olake.io/docs/connectors/mysql/setup/rds/)
- **Oracle** (https://olake.io/docs/connectors/oracle/): i/o timeout fixed with the TIMEOUT JDBC parameter; usernames are uppercased.
- **MSSQL** (https://olake.io/docs/connectors/mssql/): ApplicationIntent=ReadOnly for replicas; CDC retention defaults to 3 days.
- **DB2** (https://olake.io/docs/connectors/db2/): SQL0668N needs a REORG; RUNSTATS is required.
- **Kafka** (https://olake.io/docs/connectors/kafka/): recovering from consumer-group corruption; topic_pattern.
- **S3 source** (https://olake.io/docs/connectors/s3/): incremental sync uses _last_modified_time.
- **Data filter:** at most 2 conditions and requires normalization (https://olake.io/docs/understanding/terminologies/olake/).
- **Clear Destination** triggers and the Kafka consumer-group cases (https://olake.io/docs/getting-started/job-level-properties/).
- **Parquet writer:**
  - key=value partition_regex with granularity (https://olake.io/docs/writers/parquet/partitioning/)
  - max_file_size_mb defaults to 512; output is Snappy-compressed (https://olake.io/docs/writers/parquet/config/)
- **REST catalogs** (https://olake.io/docs/writers/iceberg/catalog/rest/): S3 Tables setup (catalog_type s3tables, rest_signing_name s3tables); Unity needs no_identifier_fields=true.
- **Compose settings** (https://olake.io/docs/install/olake-ui/): LOG_RETENTION_PERIOD 30 days, TEMPORAL_RETENTION_PERIOD 168h, TELEMETRY_DISABLED, KMS encryption, OLAKE_STORAGE_MODE=s3.
- **Playground ports** (https://olake.io/docs/getting-started/playground/).
- **Helm jobProfiles** (https://olake.io/docs/install/kubernetes/).

**Files kept** (188 KB) under (probe script in a deleted scratch dir):
- notes/questions.json (the 40 items plus their evidence quotes)
- notes/bm25_probe.txt
- notes/cited_lastupdated.txt
- notes/docs_urls.txt
- notes/mock/*.jsonl
- scripts/html2text.py, validate.py, bm25_probe.py, score.py, render_questions.py
- scripts/fetch_sources.sh, which re-creates the source copies I deleted

Deleted at the end: clones/ (11 MB), pages/ (12 MB) and repo_files/. Nothing was written to the git worktree; its `git status` shows only other agents' untracked poc/ files.

## questions (40)
- **SET-01** [SET/answerable/easy/verified=True] fastest way to get olake ui running on my laptop? and whats the default login
  - sources: https://olake.io/docs/getting-started/quickstart/
  - must: one command: curl the olake-ui docker-compose-v1.yml and pipe it to `docker compose -f - up -d`; UI is served at http://localhost:8000 (port 8000 must be free); default credentials admin / password
  - behavior: answer
  - note: Opened /docs/getting-started/quickstart/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SET-02** [SET/answerable/easy/verified=True] How do I set my own admin username/password instead of the default one before bringing up the OLake UI docker compose stack?
  - sources: https://olake.io/docs/install/olake-ui/
  - must: edit the `x-signup-defaults` block in the compose file; set username, password (and email) there before the first start; the signup-init service creates the admin user from these values
  - behavior: answer
  - note: Opened /docs/install/olake-ui/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **SET-03** [SET/answerable/easy/verified=True] Not using the UI at all. How do I generate streams.json for a Postgres source with just Docker?
  - sources: https://olake.io/docs/install/docker-cli/
  - must: run the `olakego/source-postgres` image with the `discover` command; mount the config folder at /mnt/config and pass `--config /mnt/config/source.json`; discover writes streams.json (pin a version tag instead of :latest for production)
  - behavior: answer
  - note: Opened /docs/install/docker-cli/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SET-04** [SET/answerable/medium/verified=True] olake discover keeps timing out on a postgres db with ~4k tables. how do i give it more time or more parallelism?
  - sources: https://olake.io/docs/install/docker-cli/ | https://olake.io/docs/getting-started/job-level-properties/
  - must: CLI: `--timeout <seconds>` overrides the default discover timeout of 300 s (5 min); CLI: `--max-discover-threads` (default 50, must be >= 1) controls parallel schema discovery; UI: raise the Max Discover Threads job setting (values above the stream count add nothing)
  - behavior: answer
  - note: Opened /docs/install/docker-cli/, /docs/getting-started/job-level-properties/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Lexically hardest item in the BM25 probe (best expected page only at rank 12).
- **SET-05** [SET/answerable/easy/verified=True] helm install of olake on EKS - what are the commands and how do I open the UI afterwards?
  - sources: https://olake.io/docs/install/kubernetes/
  - must: `helm repo add olake https://datazip-inc.github.io/olake-helm` then `helm repo update`; on EKS: `helm install olake olake/olake --set global.storageClass="gp2"`; `kubectl port-forward svc/olake-ui 8000:8000` (or use an Ingress), login admin/password
  - behavior: answer
  - note: Opened /docs/install/kubernetes/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **SET-06** [SET/answerable/hard/verified=True] The docker compose docs list a 'Temporal UI' component for debugging workflows, but after the one-line compose up there's no temporal-ui container running. Where is it / how do I get it?
  - sources: https://olake.io/docs/install/olake-ui/ | https://github.com/datazip-inc/olake-ui/blob/master/docker-compose-v1.yml | https://github.com/datazip-inc/olake-ui/blob/master/README.md
  - must: in docker-compose-v1.yml the `temporal-ui` service sits under the `debug` compose profile, so it is not started by default; start it with `--profile debug` (e.g. `docker compose --profile debug ... up -d`); it is published on host port 8081 (container port 8080)
  - behavior: answer
  - note: Opened /docs/install/olake-ui/, gh:olake-ui:docker-compose-v1.yml and gh:olake-ui:README.md on 2026-10-16 (curl/raw, read as text); 4 quoted evidence snippets matched by scripts/validate.py. The compose file puts temporal-ui under `profiles: [debug]` with ports 8081:8080. The README shows the same `--profile <name>` activation pattern (for fusion), so `--profile debug` is how to start it by analogy.
- **SET-07** [SET/negative/easy/verified=True] can i use a quartz cron like `0 0/15 * ? * MON-FRI` as the custom frequency for a job?
  - sources: https://olake.io/docs/getting-started/job-level-properties/
  - must: Quartz cron syntax is not supported; custom frequency accepts standard 5-field cron (min hour dom month dow) or 7-field cron (sec min hour dom month dow year); built-in options: every minute, hourly, daily, weekly
  - behavior: answer: not supported, cite the support list
  - note: Opened /docs/getting-started/job-level-properties/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **SRC-01** [SRC/answerable/easy/verified=True] Setting up CDC on RDS Postgres. wal_level shows 'replica' and the default parameter group won't let me edit it. what do i need to do?
  - sources: https://olake.io/docs/connectors/postgres/setup/rds/
  - must: create/attach a custom DB parameter group (the default one cannot be modified); set `rds.logical_replication = 1` (this sets wal_level to logical) and reboot the instance; CDC user needs the `rds_replication` role (master user already has it); automated backups must be enabled
  - behavior: answer
  - note: Opened /docs/connectors/postgres/setup/rds/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SRC-02** [SRC/answerable/easy/verified=True] postgres CDC job dies with `Failed with non retryable error: LSN not updated after 5 mins`. what does that mean and how do i fix it?
  - sources: https://olake.io/docs/connectors/postgres/
  - must: `wal_sender_timeout` on the Postgres server is too low (e.g. 30s), so Postgres closes the replication connection before the LSN is acknowledged; set `wal_sender_timeout` to 0 (recommended) or a large value; more likely under concurrent writes / heavy CDC load
  - behavior: answer
  - note: Opened /docs/connectors/postgres/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **SRC-03** [SRC/answerable/medium/verified=True] trying to do CDC from a Supabase postgres. which supabase connection mode do I use? my olake docker container can't even reach the direct host
  - sources: https://olake.io/docs/connectors/postgres/
  - must: CDC requires Supabase's Direct Connection (replication slots can only be created over the direct connection); Direct Connection is IPv6-only by default (IPv4 needs Supabase's paid IPv4 add-on); Docker is IPv4-only by default: enable IPv6 by adding "ipv6": true in Docker Engine settings (or use the IPv4 add-on)
  - behavior: answer
  - note: Opened /docs/connectors/postgres/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SRC-04** [SRC/answerable/easy/verified=True] mysql cdc prereqs?
  - sources: https://olake.io/docs/connectors/mysql/
  - must: binary logging on with row format: log_bin=ON, binlog_format=ROW, binlog_row_image=FULL (binlog_row_metadata=FULL recommended); unique server-id on the server; user needs REPLICATION SLAVE, REPLICATION CLIENT and SELECT; MySQL 5.7+
  - behavior: answer
  - note: Opened /docs/connectors/mysql/ on 2026-10-16 (curl/clone, read as text); 5 quoted evidence snippets matched by scripts/validate.py.
- **SRC-05** [SRC/answerable/hard/verified=True] Is binlog_row_metadata=FULL actually mandatory for MySQL CDC? Our managed MySQL won't let us change it and the docs list it under prerequisites.
  - sources: https://olake.io/docs/connectors/mysql/ | https://olake.io/docs/release/ingestion/v0.10.0/
  - must: not mandatory since OLake Go v0.10.0 (CDC works without binlog_row_metadata=FULL); test connection reports it as an optional check; FULL is still recommended: without it OLake reads column metadata from information_schema; risk without it: columns can be mis-mapped (e.g. 'Column Count Mismatch') if a table is altered while a sync is catching up
  - behavior: answer
  - note: Opened /docs/connectors/mysql/, /docs/release/ingestion/v0.10.0/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Version-sensitive: the connector page still lists binlog_row_metadata=FULL under CDC prerequisites while the v0.10.0 release notes and the test-connection section make it optional.
- **SRC-06** [SRC/answerable/medium/verified=True] mongo cdc - what do I need on the mongo side? self-hosted mongo 6 running as a single standalone node right now
  - sources: https://olake.io/docs/connectors/mongodb/ | https://olake.io/docs/connectors/mongodb/cdc_setup/
  - must: MongoDB 4.0+ running as a replica set (e.g. start with `--replSet rs0`, then `rs.initiate()`), which enables the oplog; user (created in admin) with read on the `local` db (oplog) plus readWrite on the app db; Atlas already runs replica sets; without a replica set only Full Refresh / Incremental are possible
  - behavior: answer
  - note: Opened /docs/connectors/mongodb/, /docs/connectors/mongodb/cdc_setup/ on 2026-10-16 (curl/clone, read as text); 5 quoted evidence snippets matched by scripts/validate.py.
- **SRC-07** [SRC/answerable/medium/verified=True] oracle full refresh fails with `ORA-01031: insufficient privileges` even though the user has SELECT on the table??
  - sources: https://olake.io/docs/connectors/oracle/setup/generic/ | https://olake.io/docs/connectors/oracle/
  - must: grant `FLASHBACK ON <owner>.<table>` - chunk reads use `SELECT ... AS OF SCN` flashback queries (ORA-01031 without it); also grant `EXECUTE ON DBMS_FLASHBACK` (needed to fetch the current SCN; ORA-00904 without it); base grants: CREATE SESSION and SELECT ON <owner>.<table>
  - behavior: answer
  - note: Opened /docs/connectors/oracle/setup/generic/, /docs/connectors/oracle/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SRC-08** [SRC/negative/easy/verified=True] Does OLake support Oracle CDC via LogMiner? We need change capture from a 19c database.
  - sources: https://olake.io/docs/connectors/oracle/ | https://olake.io/docs/ | https://github.com/datazip-inc/olake/blob/master/drivers/oracle/internal/cdc.go
  - must: Oracle CDC (LogMiner or otherwise) is not supported; Oracle supports only Full Refresh and Full Refresh + Incremental; alternative: Full Refresh + Incremental with a cursor column (e.g. updated_at)
  - behavior: answer: not supported, cite the support list
  - note: Opened /docs/connectors/oracle/, /docs/, gh:olake:drivers/oracle/internal/cdc.go on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py. Trap for the bot: /docs/core/configs/source/ mentions an Oracle 'LogMiner setup' and the repo README marks Oracle CDC as WIP; the driver stub (repo commit d20c68e) says CDC is not supported yet.
- **SRC-09** [SRC/answerable/easy/verified=True] how do I turn on CDC for a SQL Server running on Amazon RDS so olake can read it?
  - sources: https://olake.io/docs/connectors/mssql/
  - must: enable CDC on the database: on RDS `EXEC msdb.dbo.rds_cdc_enable_db` (self-managed: `sys.sp_cdc_enable_db`); enable CDC per table with `sys.sp_cdc_enable_table`; SQL Server 2017+; user needs SELECT on the table schemas and the `cdc` schema, VIEW DATABASE STATE (2022+: VIEW DATABASE PERFORMANCE STATE), SELECT on msdb.dbo.cdc_jobs
  - behavior: answer
  - note: Opened /docs/connectors/mssql/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SRC-10** [SRC/answerable/medium/verified=True] added a column to a mssql table that's in a CDC job and the new column never shows up in iceberg. what am i missing
  - sources: https://olake.io/docs/connectors/mssql/
  - must: SQL Server CDC does not add new columns to the existing capture instance after DDL; create a new capture instance (sys.sp_cdc_enable_table with a new capture_instance name); OLake switches to the newest one automatically; or enable Manage Capture Instance (`manage_capture_instances`), which requires db_owner on the source DB
  - behavior: answer
  - note: Opened /docs/connectors/mssql/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Phrased in user terms rather than doc terms; BM25 ranks the MSSQL page only 30th (schema-evolution pages dominate), so it tests dense/hybrid retrieval.
- **SRC-11** [SRC/answerable/easy/verified=True] DB2 source fails on our graviton (arm64) linux box but works on my intel laptop. known issue?
  - sources: https://olake.io/docs/connectors/db2/
  - must: the IBM Data Server ODBC and CLI driver is not supported on Linux arm64; run DB2 syncs on AMD64 (recommended architecture); DB2 LUW 11.5.3 or higher
  - behavior: answer
  - note: Opened /docs/connectors/db2/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **SRC-12** [SRC/answerable/easy/verified=True] our kafka topics are avro with confluent schema registry (basic auth). what do i need in the kafka source config?
  - sources: https://olake.io/docs/connectors/kafka/
  - must: configure `schema_registry` with its `endpoint` - mandatory for AVRO topics; registry auth: `username` + `password` (or `bearer_token`); UI auth types No Auth / Username & Password / Bearer Token; without a schema registry messages are treated as JSON (only JSON and AVRO payloads are supported)
  - behavior: answer
  - note: Opened /docs/connectors/kafka/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SRC-13** [SRC/answerable/hard/verified=True] Our MSK cluster only exposes a TLS listener (no SASL). The kafka docs page only shows PLAINTEXT / SASL_PLAINTEXT / SASL_SSL - can OLake connect at all?
  - sources: https://olake.io/docs/connectors/kafka/ | https://github.com/datazip-inc/olake/blob/master/drivers/kafka/README.md | https://github.com/datazip-inc/olake/blob/master/drivers/kafka/resources/spec.json
  - must: yes: the driver also supports `security_protocol: "SSL"` (TLS without SASL) - documented in the repo driver README and spec.json, not on the docs page; custom CA / mTLS via `ssl.server_ca`, `ssl.client_cert`, `ssl.client_key` (all optional); for AWS MSK (broker certs managed by AWS) just set `"security_protocol": "SSL"` with no certificates
  - behavior: answer
  - note: Opened /docs/connectors/kafka/, gh:olake:drivers/kafka/README.md, gh:olake:drivers/kafka/resources/spec.json on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Docs gap: the docs page lists 3 protocols; the driver README and spec.json (which renders the UI form) add a 4th, SSL. Repo files read at commit d20c68e (2026-10-15).
- **SRC-14** [SRC/answerable/easy/verified=True] S3 source: my bucket has s3://lake/raw/orders/2024-01-01/part-1.csv.gz, s3://lake/raw/orders/2024-01-02/part-2.csv.gz and s3://lake/raw/customers/customers.csv. how does olake turn that into tables and what IAM perms does it need?
  - sources: https://olake.io/docs/connectors/s3/
  - must: one stream per top-level folder under the path prefix -> streams `orders` and `customers` (set path_prefix `raw/`, file_format csv); gzip (.csv.gz) is detected automatically; IAM: s3:ListBucket on the bucket and s3:GetObject on bucket/*; keys optional (default AWS credential chain)
  - behavior: answer
  - note: Opened /docs/connectors/s3/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-01** [SYNC/answerable/easy/verified=True] full refresh + incremental vs full refresh + cdc - if a row gets deleted in the source, does incremental remove it?
  - sources: https://olake.io/docs/understanding/terminologies/olake/
  - must: incremental re-reads only rows whose cursor value is greater than the last synced max (primary cursor, optional fallback cursor); deletes are never captured by incremental; updates only if the cursor is something like updated_at (an id cursor only picks new rows); Full Refresh + CDC does an initial full load then streams inserts, updates and deletes from the change log
  - behavior: answer
  - note: Opened /docs/understanding/terminologies/olake/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-02** [SYNC/answerable/medium/verified=True] whats the diff between cdc and strict_cdc in supported_sync_modes? i dont want to re-copy a 2TB table, only changes from now on
  - sources: https://olake.io/docs/understanding/terminologies/olake/ | https://olake.io/docs/install/docker-cli/ | https://github.com/datazip-inc/olake/blob/master/drivers/abstract/cdc.go
  - must: `cdc` = Full Refresh + CDC: initial backfill/snapshot, then change capture; `strict_cdc` = the 'CDC Only' mode: backfill is skipped, only changes after CDC starts are synced; so strict_cdc avoids the re-copy, but existing rows are never loaded into the destination
  - behavior: answer
  - note: Opened /docs/understanding/terminologies/olake/, /docs/install/docker-cli/, gh:olake:drivers/abstract/cdc.go on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Docs never state strict_cdc == 'CDC Only' verbatim; the mapping is confirmed in drivers/abstract/cdc.go (STRICTCDC streams log 'backfill not enabled' and skip the backfill).
- **SYNC-03** [SYNC/answerable/medium/verified=True] running the CLI from a k8s cronjob. how does the next run resume CDC, and what position does the state file keep for postgres vs mysql vs mongo?
  - sources: https://olake.io/docs/install/docker-cli/
  - must: pass `--state /mnt/config/state.json` to `sync`; the file is created/updated automatically and must persist between runs; Postgres: global LSN (`global.state.lsn`); MySQL: global binlog file + position (`Name`/`Pos`) plus `server_id`; MongoDB: no global section - per-stream resume token in `state._data`
  - behavior: answer
  - note: Opened /docs/install/docker-cli/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-04** [SYNC/answerable/easy/verified=True] if I hit Cancel on a running job, does the next run start from scratch?
  - sources: https://olake.io/docs/getting-started/job-level-properties/
  - must: cancel stops at a safe checkpoint; already-synced data stays in the destination (no rollback); Full Refresh has no state file, so the next run reloads everything; Full Refresh + CDC, Full Refresh + Incremental and Strict CDC keep state and resume; cancellation can take up to ~1 minute
  - behavior: answer
  - note: Opened /docs/getting-started/job-level-properties/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-05** [SYNC/negative/medium/verified=True] We changed column `price` from INTEGER to TEXT in Postgres. Will OLake change the Iceberg column to string automatically and keep syncing?
  - sources: https://olake.io/docs/features/schema/
  - must: not supported: writing STRING values into an existing INT/LONG/FLOAT/DOUBLE column fails the sync; only widening promotions are applied automatically (INT->LONG, FLOAT->DOUBLE, DATE->TIMESTAMP, DECIMAL precision increase); the reverse direction (numeric values into an existing STRING column) is handled; a DLQ column for other incompatible changes is only 'coming soon'
  - behavior: answer: not supported, cite the support list
  - note: Opened /docs/features/schema/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Direction matters: numeric values arriving into an existing STRING column are converted and kept (supported); STRING into an existing INT column fails (this question).
- **SYNC-06** [SYNC/answerable/medium/verified=True] added a new column to a postgres table that olake ui is already syncing. will it show up in iceberg, and will the old rows get values?
  - sources: https://olake.io/docs/features/schema/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: schema discovery detects it and adds it to the Iceberg schema when 'Sync new columns automatically' (sync_new_columns, on by default) is enabled; otherwise select it via Edit Streams; existing rows are not backfilled - they stay NULL; to populate old rows run Clear Destination and a full reload (a sparse new column appears only once a non-NULL value arrives)
  - behavior: answer
  - note: Opened /docs/features/schema/, /docs/understanding/terminologies/olake/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-07** [SYNC/answerable/medium/verified=True] kafka topic gets lots of updates per customer_id and I only want the latest record per customer in iceberg, not every event. how?
  - sources: https://olake.io/docs/connectors/kafka/ | https://olake.io/docs/install/docker-cli/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: switch the stream from the default Append to Upsert and set a Deduplication Key (`dedup_keys`, e.g. ["customer_id"]); Kafka upsert supports positional deletes only: `update_type: "pos"`, `append_mode: false`; needs OLake Go >= 0.12.1 and OLake UI >= 0.7.1; don't increase the topic's partition count while an upsert job runs
  - behavior: answer
  - note: Opened /docs/connectors/kafka/, /docs/install/docker-cli/, /docs/understanding/terminologies/olake/ on 2026-10-16 (curl/clone, read as text); 5 quoted evidence snippets matched by scripts/validate.py. Fresh/version-sensitive: Kafka upsert shipped in OLake v0.12.1 (GitHub release 2026-10-15); the docs release-notes section stops at v0.12.0.
- **SYNC-08** [SYNC/answerable/hard/verified=True] why do my mongo collections land in iceberg as a single `data` JSON string column while my postgres tables come out as proper columns? same job settings otherwise
  - sources: https://olake.io/docs/understanding/terminologies/olake/ | https://github.com/datazip-inc/olake/blob/master/drivers/abstract/abstract.go | https://github.com/datazip-inc/olake/blob/master/constants/constants.go
  - must: normalization is on by default only for relational sources (Postgres, MySQL, Oracle, DB2, MSSQL); MongoDB (and S3/Kafka) streams default to normalization off; with normalization off the whole record is stored as a JSON string in the `data` column; turn on Normalization for the stream ("normalization": true) to get level-1 flattening into columns
  - behavior: answer
  - note: Opened /docs/understanding/terminologies/olake/, gh:olake:drivers/abstract/abstract.go, gh:olake:constants/constants.go on 2026-10-16 (curl/clone, read as text); 5 quoted evidence snippets matched by scripts/validate.py. Also checked olake-ui ui/src/modules/ingestion/features/jobs/utils/streams.ts: the UI seeds unselected streams from default_stream_properties (fallback normalization=false).
- **SYNC-09** [SYNC/answerable/easy/verified=True] postgres numeric(12,2) money columns show up as float in iceberg, I expected decimal. bug?
  - sources: https://olake.io/docs/connectors/postgres/
  - must: documented behaviour: Postgres float/float4/real/numeric map to `float` in the destination (no decimal mapping listed); double precision/float8 map to `double`; date/timestamp types map to `timestamptz`, always ingested in UTC
  - behavior: answer
  - note: Opened /docs/connectors/postgres/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-10** [SYNC/answerable/easy/verified=True] mysql full refresh fails on one table with `failed to get or split chunks`. ideas?
  - sources: https://olake.io/docs/connectors/mysql/
  - must: cause: table statistics not populated, or the table has 0 rows (chunking relies on stats); fix: run `ANALYZE TABLE <namespace>.<table_name>;` then retry
  - behavior: answer
  - note: Opened /docs/connectors/mysql/ on 2026-10-16 (curl/clone, read as text); 2 quoted evidence snippets matched by scripts/validate.py.
- **SYNC-11** [SYNC/answerable/hard/verified=True] is `initial_wait_time: 10` in our mysql source.json actually honored? we copied it from the docs example
  - sources: https://olake.io/docs/connectors/mysql/ | https://github.com/datazip-inc/olake/blob/master/drivers/mysql/internal/mysql.go
  - must: no: the current MySQL driver enforces a 120-second minimum; anything lower is raised to 120 with a warning in the logs; initial_wait_time is how long the binlog syncer waits (idle) before exiting / while locating the saved position; the docs example value (10) is below the enforced minimum - raise it further if you hit 'Idle Timeout Reached, Exiting Binlog Syncer'
  - behavior: answer
  - note: Opened /docs/connectors/mysql/, gh:olake:drivers/mysql/internal/mysql.go on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py. Doc/code drift: docs example uses 10; the MySQL driver raises values below 120 to 120 (the Postgres driver instead falls back to 10800 when below 120). Repo commit d20c68e.
- **DST-01** [DST/answerable/easy/verified=True] minimal destination.json for iceberg on aws glue?
  - sources: https://olake.io/docs/writers/iceberg/catalog/glue/
  - must: "type": "ICEBERG" with writer.catalog_type "glue"; required: iceberg_s3_path (s3://bucket/) and aws_region; aws_access_key/secret_key optional when IAM roles are used; for Glue the catalog name is fixed to olake_iceberg; IAM needs Glue table/database actions plus S3 read/write
  - behavior: answer
  - note: Opened /docs/writers/iceberg/catalog/glue/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **DST-02** [DST/answerable/medium/verified=True] iceberg to a local minio with a postgres JDBC catalog - what do I set for s3_endpoint / ssl / path style? connection errors when I use localhost
  - sources: https://olake.io/docs/writers/iceberg/catalog/jdbc/
  - must: catalog_type "jdbc" with jdbc_url, jdbc_username, jdbc_password, plus iceberg_s3_path and aws_region; `s3_endpoint` = the MinIO URL, `s3_path_style: true` (MinIO needs path-style), `s3_use_ssl: false` for an http:// endpoint; from inside Docker use host.docker.internal (or the container name) instead of localhost
  - behavior: answer
  - note: Opened /docs/writers/iceberg/catalog/jdbc/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **DST-03** [DST/answerable/medium/verified=True] can olake write plain parquet into a GCS bucket? how do credentials work there
  - sources: https://olake.io/docs/writers/parquet/config/ | https://olake.io/docs/writers/parquet/gcs/
  - must: yes - use the Parquet (S3) writer against GCS's S3-compatible API with s3_endpoint `https://storage.googleapis.com`; create HMAC keys for a service account and use them as s3_access_key / s3_secret_key; s3_bucket is the bucket name without gs://; the service account needs storage bucket/object permissions
  - behavior: answer
  - note: Opened /docs/writers/parquet/config/, /docs/writers/parquet/gcs/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **DST-04** [DST/answerable/medium/verified=True] how do we land iceberg tables on azure adls gen2?
  - sources: https://olake.io/docs/writers/iceberg/azure/
  - must: use an Iceberg REST catalog (the guide uses Lakekeeper) with an Azure/ADLS Gen2 warehouse; storage account needs Hierarchical namespace enabled; service principal with Storage Blob Data Owner and Storage Blob Delegator roles; OLake destination: Catalog Type REST, REST Catalog URL, S3 Endpoint `https://<account>.dfs.core.windows.net`, AWS keys left empty
  - behavior: answer
  - note: Opened /docs/writers/iceberg/azure/ on 2026-10-16 (curl/clone, read as text); 4 quoted evidence snippets matched by scripts/validate.py.
- **DST-05** [DST/answerable/easy/verified=True] partition an iceberg table by day(created_at) and also bucket user_id - whats the partition_regex syntax?
  - sources: https://olake.io/docs/writers/iceberg/partitioning/
  - must: `"partition_regex": "/{created_at, day}/{user_id, bucket[N]}"` (one /{field, transform} segment per level); transforms: identity, year, month, day, hour, bucket[N], truncate[N], void; don't stack redundant time transforms on the same column (e.g. day + hour of the same ts)
  - behavior: answer
  - note: Opened /docs/writers/iceberg/partitioning/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **DST-06** [DST/negative/easy/verified=True] can olake write CSV or JSON files to S3 instead of parquet?
  - sources: https://olake.io/docs/writers/parquet/config/ | https://olake.io/docs/
  - must: not supported: destinations are Apache Iceberg tables or Parquet files only; the file writer's `type` only accepts "PARQUET" (files are SNAPPY-compressed)
  - behavior: answer: not supported, cite the support list
  - note: Opened /docs/writers/parquet/config/, /docs/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **DST-07** [DST/answerable/medium/verified=True] we query the tables with Athena - can we use deletion vectors for upserts? which delete format should we pick?
  - sources: https://olake.io/docs/understanding/compatibility-engines/ | https://olake.io/docs/getting-started/job-level-properties/
  - must: Athena reads equality and positional deletes but not deletion vectors (DVs are the Iceberg v3 format); use equality (default) or positional deletes; select Athena as Target Query Engine so the Streams page only offers compatible upsert types (OLake UI 0.6.0+)
  - behavior: answer
  - note: Opened /docs/understanding/compatibility-engines/, /docs/getting-started/job-level-properties/ on 2026-10-16 (curl/clone, read as text); 3 quoted evidence snippets matched by scripts/validate.py.
- **DST-08** [DST/answerable/hard/verified=True] we switched upsert type to positional deletes on our helm deployment. anything extra to set up so syncs don't keep rebuilding stuff / failing?
  - sources: https://olake.io/docs/install/kubernetes/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: positional deletes / deletion vectors need a persistent Pebble index; the Helm chart provisions a per-job PVC `olake-index-<JobID>` (configured under `jobIndexes`, default 20Gi, can only grow); every component must be new enough: OLake >= 0.11.0, OLake UI >= 0.6.0, Helm chart >= 0.0.28, worker >= 0.3.11; keep the job pod in the PVC's availability zone (else Pending) - e.g. node affinity via jobProfiles or a single AZ
  - behavior: answer
  - note: Opened /docs/install/kubernetes/, /docs/understanding/terminologies/olake/ on 2026-10-16 (curl/clone, read as text); 5 quoted evidence snippets matched by scripts/validate.py. Version-sensitive: per-job index PVCs need OLake >=0.11.0, UI >=0.6.0, Helm chart >=0.0.28, worker >=0.3.11.
