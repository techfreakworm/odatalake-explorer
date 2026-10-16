Research agent output, 2026-10-16; evidence for docs/research.md

# verify-eval-ingestion

## changes
I kept all 40 items and dropped none. All 40 are verified=true, some only after fixes. The set is 36 answerable and 4 negative (SET-07, SRC-08, SYNC-05, DST-06); it has no unanswerable, out-of-scope or adversarial items, so those checks did not apply. 17 items changed content, 8 only got richer notes, and 15 were verified as-is.

**One wrong fact, one rewrite, one stale cause:**
- **SRC-14 had a wrong expected fact.** It said `.csv.gz` files are "detected automatically". In code they are only picked up when `compression: gzip` is set; the default is `none`, which silently skips them. A bot that answers from the docs alone will get this wrong.
- **SYNC-09 was rewritten.** The docs say Postgres `numeric` lands as `float`; the driver code maps it to Iceberg `double`.
- **SYNC-10 was narrowed.** The docs' "table has 0 rows" cause is stale: current code skips truly empty tables.

**How it was checked:**
- **Sources.** All 36 original sources return HTTP 200 at the exact URL. So do the 9 I added and the AWS page used for SRC-09. Every olake.io source is the trailing-slash form listed in https://olake.io/sitemap.xml (275 entries, 124 under /docs/); the slashless forms 301 to it.
- **Evidence.** I matched 258 short evidence snippets against the sources: 258/258 on the first pass, and 258/258 again after a full fresh download.
- **Repo heads used:** olake d20c68e, olake-ui 56826cf, olake-helm c63f10c, olake-docs d060071. I read code only and never ran anything.

**report.md was not written.** The harness blocks subagents from writing report .md files, so this field is the report. The verified set, the evidence snippets and a re-check script are in the scratchpad (paths in `report_path`).

**Content fixes, with reasons:**
1. **SRC-14:** wrong fact fixed; difficulty easy -> hard; added drivers/s3/internal/s3.go and config.go as sources.
   - In `matchesFileFormat` (s3.go), a `.csv.gz` key matches only when compression is gzip; config.go defaults compression to `none` and CSV extensions to `.csv`.
   - The S3 spec default is `none`, and the mixed plain/gzip test fixture tests/s3/testdata/csv/source.json sets `"compression": "gzip"`.
   - New fact 2: set Compression Type to gzip; decompression then happens per file by the `.gz` extension.
2. **SYNC-09:** question, facts and sources rewritten (added drivers/postgres/internal/datatype_conversion.go).
   - The docs table says numeric -> float; the code maps numeric/decimal to Float64, which becomes Iceberg double, so "show up as float" became "floating-point".
   - Dropped the off-topic timestamptz/UTC fact and the tangential double fact.
   - New facts: not a bug, there is no DECIMAL mapping, and no documented option keeps DECIMAL. An answer saying float or double should pass.
3. **SYNC-10:** fact 1 now requires only the statistics cause.
   - drivers/mysql/internal/backfill.go fails only when the stats estimate is 0 but rows exist; a truly empty table is skipped with a warning.
4. **SET-02:** added README.md and docker-compose-v1.yml as sources.
   - The docs page only implied that signup-init creates the admin from x-signup-defaults. The compose file shows it, and the README says the admin is created on first startup.
5. **SET-06:** removed "for debugging workflows" from the question; it hinted at the `debug` profile name.
6. **SRC-02:** the question now quotes the exact emitted error, "failed with non retryable error: LSN not updated after 5 minutes" (pkg/waljs/replicator.go). The old text said "5 mins".
7. **SRC-04:** fact 1 accepts binlog_row_metadata as optional/recommended. The page lists it as required, but its own test-connection section and prerequisites.go treat it as optional.
8. **SRC-06:** dropped the Atlas clause, which is off-topic for a self-hosted user. Fact 3 is now: a standalone node cannot do CDC; only Full Refresh and Incremental work.
9. **SRC-09:** fact 1 accepts AWS's form `exec msdb.dbo.rds_cdc_enable_db 'db'`. OLake docs omit the argument; the AWS RDS guide (Appendix.SQLServer.CommonDBATasks.CDC.html) passes it.
10. **SRC-11:** dropped the DB2 11.5.3 "LUW" fact. It is off-topic for the arm64 question, and the page never says "LUW".
11. **SYNC-02:** added the UI source SyncModeSectionView.tsx. It is the only place that maps strict_cdc to the "CDC Only" label and cdc to "Full Refresh + CDC".
12. **SYNC-03:** fact 1 wording. State is written to `<config folder>/state.json` by default (protocol/root.go) and read only when `--state` is passed (protocol/sync.go).
13. **SYNC-05:** facts 2 and 3.
    - The full promotion list is no longer required; the code only promotes int->long and float->double. The DLQ is no longer required either.
    - Fact 3 now tests the direction trap: the schema page's "INT -> STRING handled" case means numeric values going into an existing STRING column.
14. **SYNC-06:** dropped the `sync_new_columns` key. It appears only on the CLI page, which is not a source for this item, and the question is about the UI.
15. **DST-03:** added /docs/writers/parquet/permission/, which lists the GCS role permissions that fact 3 relies on.
16. **DST-05:** replaced two tangential facts (the full transform list, and the redundant-transform warning, which does not apply to day + bucket) with bucket[N] semantics and where to set partition_regex.
17. **DST-07:** added the terminologies page, which documents the default-format order behind "equality (default)".

**Note-only, verified:**
- **SET-04:** the UI never passes `--timeout`, so Max Discover Threads is the only UI lever. The Postgres `schemas` field also narrows discovery.
- **SET-07:** the UI's jobs.ts rejects expressions that are not 5 or 7 fields and rejects Quartz tokens. A 5-field equivalent is `*/15 * * * MON-FRI`.
- **SRC-05:** the test-connection prerequisite report shipped in v0.12.1 (released 2026-10-15).
- **SRC-08:** confirmed the traps: the LogMiner mention on /docs/core/configs/source/ and the README's "WIP" for Oracle CDC.
- **SRC-13:** spec.json is what the UI renders as the source form (via the `spec` command), so SSL is selectable in the UI.
- **SYNC-08:** the rendered page carries a caption saying the data column holds the raw JSON. Turning normalization on for an already-synced stream triggers Clear Destination.
- **SYNC-11:** the 120-second minimum has applied since v0.10.0 (commit d4088e3 is in that tag). The MySQL spec has no minimum; the Postgres spec has a minimum of 120.
- **DST-08:** the Helm values.yaml confirms the 20Gi default, grow-only size and the `olake-index-<JobID>` claim name.

**Verified as-is (15):** SET-01, SET-03, SET-05, SRC-01, SRC-03, SRC-07, SRC-10, SRC-12, SYNC-01, SYNC-04, SYNC-07, DST-01, DST-02, DST-04, DST-06.

**Doc/code drift to feed the bot.** Docs-only retrieval will miss these, and they need repo or code retrieval:
- S3 gzip discovery (SRC-14).
- Postgres numeric -> double (SYNC-09).
- MySQL empty-table handling (SYNC-10).
- MySQL `initial_wait_time` minimum of 120 vs the docs example of 10 (SYNC-11).
- Kafka `SSL` protocol (SRC-13).
- strict_cdc label (SYNC-02).
- temporal-ui `debug` profile (SET-06).
- Normalization defaults (SYNC-08).

**Smaller doc slips:**
- binlog_row_metadata listed as required vs optional (SRC-04/05).
- RDS CDC procedure argument missing (SRC-09).
- LSN error wording (SRC-02).
- MSSQL version says 2017+ while the grant tabs say 2016-2019.

**Doc traps:**
- The LogMiner mention and the README's "WIP" for Oracle CDC (SRC-08).
- /docs/core/use-cases/ presents the DLQ as if it has shipped (SYNC-05).
- The Oracle connector page lists only CREATE SESSION + SELECT (SRC-07).
- The schema page's "INT -> STRING handled" case reads the wrong way round (SYNC-05).
- The docs recommend the Supabase session pooler for IPv4, but CDC needs the direct connection (SRC-03).

**Freshness:**
- 8 of the 28 docs pages used have a sitemap lastmod of 2026-10-15: the db2, kafka, mongodb, mssql, mysql, oracle, postgres and s3 connector pages.
- olake v0.12.1 and olake-ui v0.7.1 were released on 2026-10-15; the docs release notes stop at v0.12.0.
- olake-docs HEAD d060071 (2026-10-16) matched the live site on the drift-sensitive facts.
- Re-run `scripts/refetch.sh` on the morning of 2026-10-18.

**Open:** PR #1084 in v0.12.1 ("prevent first-sync lsn mismatch under concurrent write load") might bear on SRC-02. I could not read it because `gh api .../pulls/1084` was permission-denied.

## questions (40)
- **SET-01** [SET/answerable/easy/verified=True] fastest way to get olake ui running on my laptop? and whats the default login
  - sources: https://olake.io/docs/getting-started/quickstart/
  - must: one command: curl the olake-ui docker-compose-v1.yml and pipe it to `docker compose -f - up -d`; UI is served at http://localhost:8000 (port 8000 must be free); default credentials admin / password
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/getting-started/quickstart/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SET-02** [SET/answerable/easy/verified=True] How do I set my own admin username/password instead of the default one before bringing up the OLake UI docker compose stack?
  - sources: https://olake.io/docs/install/olake-ui/ | https://github.com/datazip-inc/olake-ui/blob/master/README.md | https://github.com/datazip-inc/olake-ui/blob/master/docker-compose-v1.yml
  - must: edit the `x-signup-defaults` block (username, password, email) in the compose file (docker-compose-v1.yml); do it before the first start: the stack creates the initial admin user on first startup; the one-shot signup-init service creates the admin user from these values
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/olake-ui/, gh:olake-ui/blob/master/README.md, gh:olake-ui/blob/master/docker-compose-v1.yml (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 7/7 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Added README + compose file as sources: README says the admin is created on first startup and to edit x-signup-defaults in docker-compose-v1.yml; the compose file shows signup-init reading *defaultUsername/*defaultPassword/*defaultEmail and posting to http://olake-ui:8000/signup. Practical nuance (not in docs, so not required): the one-line install pipes the file from GitHub, so the user must download it, edit it, then run `docker compose -f docker-compose-v1.yml up -d`.
- **SET-03** [SET/answerable/easy/verified=True] Not using the UI at all. How do I generate streams.json for a Postgres source with just Docker?
  - sources: https://olake.io/docs/install/docker-cli/
  - must: run the `olakego/source-postgres` image with the `discover` command; mount the config folder at /mnt/config and pass `--config /mnt/config/source.json`; discover writes streams.json (pin a version tag instead of :latest for production)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/docker-cli/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SET-04** [SET/answerable/medium/verified=True] olake discover keeps timing out on a postgres db with ~4k tables. how do i give it more time or more parallelism?
  - sources: https://olake.io/docs/install/docker-cli/ | https://olake.io/docs/getting-started/job-level-properties/
  - must: CLI: `--timeout <seconds>` overrides the default discover timeout of 300 s (5 min); CLI: `--max-discover-threads` (default 50, must be >= 1) controls parallel schema discovery; UI: raise the Max Discover Threads job setting (values above the stream count add nothing)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/docker-cli/, /docs/getting-started/job-level-properties/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Code cross-check (olake d20c68e, olake-ui 56826cf): CLI flag defaults --max-discover-threads 50 and DefaultDiscoverTimeout 5m; the UI passes --max-discover-threads from the job's Advanced Settings but never passes --timeout, so in the UI the threads setting is the only lever. Not required but useful: the Postgres source's `schemas` field limits discovery to listed schemas.
- **SET-05** [SET/answerable/easy/verified=True] helm install of olake on EKS - what are the commands and how do I open the UI afterwards?
  - sources: https://olake.io/docs/install/kubernetes/
  - must: `helm repo add olake https://datazip-inc.github.io/olake-helm` then `helm repo update`; on EKS: `helm install olake olake/olake --set global.storageClass="gp2"`; `kubectl port-forward svc/olake-ui 8000:8000` (or use an Ingress), login admin/password
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/kubernetes/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SET-06** [SET/answerable/hard/verified=True] The docker compose docs list a 'Temporal UI' component, but after the one-line compose up there's no temporal-ui container running. Where is it / how do I get it?
  - sources: https://olake.io/docs/install/olake-ui/ | https://github.com/datazip-inc/olake-ui/blob/master/docker-compose-v1.yml | https://github.com/datazip-inc/olake-ui/blob/master/README.md
  - must: in docker-compose-v1.yml the `temporal-ui` service sits under the `debug` compose profile, so it is not started by default; start it with `--profile debug` (e.g. `docker compose --profile debug ... up -d`); it is published on host port 8081 (container port 8080)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/olake-ui/, gh:olake-ui/blob/master/docker-compose-v1.yml, gh:olake-ui/blob/master/README.md (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Rewrote the question to drop 'for debugging workflows', which hinted at the `debug` profile name. Compose file (olake-ui 56826cf) has temporal-ui under `profiles: [debug]` with ports 8081:8080 (legacy docker-compose.yml is the same). No docs page mentions the debug profile; `--profile debug` follows standard Compose semantics and the README's `--profile fusion` pattern.
- **SET-07** [SET/negative/easy/verified=True] can i use a quartz cron like `0 0/15 * ? * MON-FRI` as the custom frequency for a job?
  - sources: https://olake.io/docs/getting-started/job-level-properties/
  - must: Quartz cron syntax is not supported; custom frequency accepts standard 5-field cron (min hour dom month dow) or 7-field cron (sec min hour dom month dow year); built-in options: every minute, hourly, daily, weekly
  - behavior: answer: not supported, cite the support list
  - note: Adversarial re-check 2026-10-16: opened /docs/getting-started/job-level-properties/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Code cross-check: olake-ui ui/src/modules/ingestion/features/jobs/utils/jobs.ts rejects expressions that do not have 5 or 7 fields and rejects Quartz tokens (?, L, W, #). The example is 6 fields and contains '?', so it fails both checks. Helpful extra (not required): the 5-field equivalent is `*/15 * * * MON-FRI`.
- **SRC-01** [SRC/answerable/easy/verified=True] Setting up CDC on RDS Postgres. wal_level shows 'replica' and the default parameter group won't let me edit it. what do i need to do?
  - sources: https://olake.io/docs/connectors/postgres/setup/rds/
  - must: create/attach a custom DB parameter group (the default one cannot be modified); set `rds.logical_replication = 1` (this sets wal_level to logical) and reboot the instance; CDC user needs the `rds_replication` role (master user already has it); automated backups must be enabled
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/postgres/setup/rds/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SRC-02** [SRC/answerable/easy/verified=True] postgres CDC job dies with `failed with non retryable error: LSN not updated after 5 minutes`. what does that mean and how do i fix it?
  - sources: https://olake.io/docs/connectors/postgres/
  - must: `wal_sender_timeout` on the Postgres server is too low (e.g. 30s), so Postgres closes the replication connection before the LSN is acknowledged; set `wal_sender_timeout` to 0 (recommended) or a large value; more likely under concurrent writes / heavy CDC load
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/postgres/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Question now quotes the exact string the code emits (pkg/waljs/replicator.go: ErrNonRetryable 'failed with non retryable error' + 'LSN not updated after 5 minutes'; it waits 5 minutes for the slot to advance). The docs heading still says 'LSN not updated after X mins'.
- **SRC-03** [SRC/answerable/medium/verified=True] trying to do CDC from a Supabase postgres. which supabase connection mode do I use? my olake docker container can't even reach the direct host
  - sources: https://olake.io/docs/connectors/postgres/
  - must: CDC requires Supabase's Direct Connection (replication slots can only be created over the direct connection); Direct Connection is IPv6-only by default (IPv4 needs Supabase's paid IPv4 add-on); Docker is IPv4-only by default: enable IPv6 by adding "ipv6": true in Docker Engine settings (or use the IPv4 add-on)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/postgres/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SRC-04** [SRC/answerable/easy/verified=True] mysql cdc prereqs?
  - sources: https://olake.io/docs/connectors/mysql/
  - must: binary logging with row events: log_bin=ON, binlog_format=ROW, binlog_row_image=FULL (binlog_row_metadata=FULL is also listed; the connection test treats it as optional/recommended); unique server-id on the server; user needs REPLICATION SLAVE, REPLICATION CLIENT and SELECT; MySQL 5.7+
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mysql/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 8/8 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Reworded the binlog_row_metadata part: the page lists it under the required binary logging settings, while its own test-connection section and the code (drivers/mysql/internal/prerequisites.go has no Required flag) treat it as optional. Either wording should pass.
- **SRC-05** [SRC/answerable/hard/verified=True] Is binlog_row_metadata=FULL actually mandatory for MySQL CDC? Our managed MySQL won't let us change it and the docs list it under prerequisites.
  - sources: https://olake.io/docs/connectors/mysql/ | https://olake.io/docs/release/ingestion/v0.10.0/
  - must: not mandatory since OLake Go v0.10.0 (CDC works without binlog_row_metadata=FULL); test connection reports it as an optional check; FULL is still recommended: without it OLake reads column metadata from information_schema; risk without it: columns can be mis-mapped (e.g. 'Column Count Mismatch') if a table is altered while a sync is catching up
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mysql/, /docs/release/ingestion/v0.10.0/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 4/4 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Freshness: the CDC prerequisite report in test connection shipped in OLake v0.12.1 (GitHub release 2026-10-15, PR #1234). The docs release notes stop at v0.12.0. The code check also passes when the variable is absent (MySQL < 8.0.1, MariaDB).
- **SRC-06** [SRC/answerable/medium/verified=True] mongo cdc - what do I need on the mongo side? self-hosted mongo 6 running as a single standalone node right now
  - sources: https://olake.io/docs/connectors/mongodb/ | https://olake.io/docs/connectors/mongodb/cdc_setup/
  - must: MongoDB 4.0+ running as a replica set (e.g. start with `--replSet rs0`, then `rs.initiate()`), which enables the oplog; user (created in admin) with read on the `local` db (oplog) plus readWrite on the app db; a standalone node cannot do CDC; without a replica set only Full Refresh / Full Refresh + Incremental (update_method Standalone) are possible
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mongodb/, /docs/connectors/mongodb/cdc_setup/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 8/8 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Dropped the Atlas clause from fact 3: the user is self-hosted, so it was off-topic and would penalise a focused answer.
- **SRC-07** [SRC/answerable/medium/verified=True] oracle full refresh fails with `ORA-01031: insufficient privileges` even though the user has SELECT on the table??
  - sources: https://olake.io/docs/connectors/oracle/setup/generic/ | https://olake.io/docs/connectors/oracle/
  - must: grant `FLASHBACK ON <owner>.<table>` - chunk reads use `SELECT ... AS OF SCN` flashback queries (ORA-01031 without it); also grant `EXECUTE ON DBMS_FLASHBACK` (needed to fetch the current SCN; ORA-00904 without it); base grants: CREATE SESSION and SELECT ON <owner>.<table>
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/oracle/setup/generic/, /docs/connectors/oracle/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 7/7 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SRC-08** [SRC/negative/easy/verified=True] Does OLake support Oracle CDC via LogMiner? We need change capture from a 19c database.
  - sources: https://olake.io/docs/connectors/oracle/ | https://olake.io/docs/ | https://github.com/datazip-inc/olake/blob/master/drivers/oracle/internal/cdc.go
  - must: Oracle CDC (LogMiner or otherwise) is not supported; Oracle supports only Full Refresh and Full Refresh + Incremental; alternative: Full Refresh + Incremental with a cursor column (e.g. updated_at)
  - behavior: answer: not supported, cite the support list
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/oracle/, /docs/, gh:olake/blob/master/drivers/oracle/internal/cdc.go (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Traps confirmed: /docs/core/configs/source/ mentions an Oracle 'LogMiner setup', and the olake README marks Oracle CDC as WIP. The Oracle connector page lists two sync modes, the /docs/ support table shows dashes for Oracle CDC, and drivers/oracle/internal/cdc.go says 'CDC is not supported yet' (d20c68e).
- **SRC-09** [SRC/answerable/easy/verified=True] how do I turn on CDC for a SQL Server running on Amazon RDS so olake can read it?
  - sources: https://olake.io/docs/connectors/mssql/
  - must: enable CDC on the database: on RDS run `msdb.dbo.rds_cdc_enable_db` (AWS's documented form passes the DB name, e.g. `exec msdb.dbo.rds_cdc_enable_db 'mydb'`) instead of `sys.sp_cdc_enable_db`; enable CDC per table with `sys.sp_cdc_enable_table`; SQL Server 2017+; user needs SELECT on the table schemas and the `cdc` schema, VIEW DATABASE STATE (2022+: VIEW DATABASE PERFORMANCE STATE), SELECT on msdb.dbo.cdc_jobs
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mssql/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 9/9 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). OLake docs show `EXEC msdb.dbo.rds_cdc_enable_db;` with no argument. The AWS RDS guide (https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.SQLServer.CommonDBATasks.CDC.html, opened 2026-10-16) passes 'database_name', so fact 1 accepts either form. Minor docs inconsistency: the version prerequisite says 2017+, but the grant tabs say 2016-2019.
- **SRC-10** [SRC/answerable/medium/verified=True] added a column to a mssql table that's in a CDC job and the new column never shows up in iceberg. what am i missing
  - sources: https://olake.io/docs/connectors/mssql/
  - must: SQL Server CDC does not add new columns to the existing capture instance after DDL; create a new capture instance (sys.sp_cdc_enable_table with a new capture_instance name); OLake switches to the newest one automatically; or enable Manage Capture Instance (`manage_capture_instances`), which requires db_owner on the source DB
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mssql/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SRC-11** [SRC/answerable/easy/verified=True] DB2 source fails on our graviton (arm64) linux box but works on my intel laptop. known issue?
  - sources: https://olake.io/docs/connectors/db2/
  - must: documented limitation: the IBM Data Server ODBC and CLI driver used by the DB2 connector is not supported on Linux arm64, so avoid arm64 machines for DB2 workloads; run DB2 syncs on AMD64 (x86_64), the recommended architecture
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/db2/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 3/3 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Dropped the 'DB2 LUW 11.5.3 or higher' fact: it does not answer the arm64 question, and the page says 'DB2 Version 11.5.3', not 'LUW'.
- **SRC-12** [SRC/answerable/easy/verified=True] our kafka topics are avro with confluent schema registry (basic auth). what do i need in the kafka source config?
  - sources: https://olake.io/docs/connectors/kafka/
  - must: configure `schema_registry` with its `endpoint` - mandatory for AVRO topics; registry auth: `username` + `password` (or `bearer_token`); UI auth types No Auth / Username & Password / Bearer Token; without a schema registry messages are treated as JSON (only JSON and AVRO payloads are supported)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/kafka/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 8/8 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SRC-13** [SRC/answerable/hard/verified=True] Our MSK cluster only exposes a TLS listener (no SASL). The kafka docs page only shows PLAINTEXT / SASL_PLAINTEXT / SASL_SSL - can OLake connect at all?
  - sources: https://olake.io/docs/connectors/kafka/ | https://github.com/datazip-inc/olake/blob/master/drivers/kafka/README.md | https://github.com/datazip-inc/olake/blob/master/drivers/kafka/resources/spec.json
  - must: yes: the driver also supports `security_protocol: "SSL"` (TLS without SASL) - documented in the repo driver README and spec.json, not on the docs page; custom CA / mTLS via `ssl.server_ca`, `ssl.client_cert`, `ssl.client_key` (all optional); for AWS MSK (broker certs managed by AWS) just set `"security_protocol": "SSL"` with no certificates
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/kafka/, gh:olake/blob/master/drivers/kafka/README.md, gh:olake/blob/master/drivers/kafka/resources/spec.json (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 9/9 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). spec.json oneOf[3] is titled 'SSL'; all ssl.* fields are optional ('all fields optional for AWS MSK'). The olake `spec` command (protocol/spec.go) serves drivers/<type>/resources/spec.json, and olake-ui renders it as the source form, so SSL is selectable in the UI even though the docs page lists only 3 protocols. Repo d20c68e.
- **SRC-14** [SRC/answerable/hard/verified=True] S3 source: my bucket has s3://lake/raw/orders/2024-01-01/part-1.csv.gz, s3://lake/raw/orders/2024-01-02/part-2.csv.gz and s3://lake/raw/customers/customers.csv. how does olake turn that into tables and what IAM perms does it need?
  - sources: https://olake.io/docs/connectors/s3/ | https://github.com/datazip-inc/olake/blob/master/drivers/s3/internal/s3.go | https://github.com/datazip-inc/olake/blob/master/drivers/s3/internal/config.go
  - must: one stream per top-level folder under the path prefix -> streams `orders` and `customers` (set path_prefix `raw/`, file_format csv); set compression to `gzip` (UI 'Compression Type'): with the default `none` only keys ending in `.csv` match, so the `.csv.gz` files under orders/ are skipped; with gzip set both `.csv` and `.csv.gz` match and each file is decompressed by its own `.gz` extension; IAM: s3:ListBucket on the bucket and s3:GetObject on bucket/*; access keys optional (default AWS credential chain)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/s3/, gh:olake/blob/master/drivers/s3/internal/s3.go, gh:olake/blob/master/drivers/s3/internal/config.go (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 14/14 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). FIXED a wrong fact. The old fact said gzip is 'detected automatically', which only holds for decompression. In olake d20c68e, drivers/s3/internal/s3.go matchesFileFormat accepts `<ext>.gz` only when compression == gzip, config.go defaults compression to `none` with CSV extensions {.csv}, and the S3 spec default is `none`. The integration fixture tests/s3/testdata/csv/source.json mixes plain and gzipped CSV and sets "compression": "gzip". The docs page ('Compression: Automatically detected from file extension') does not mention this, so this is now a doc/code-drift item.
- **SYNC-01** [SYNC/answerable/easy/verified=True] full refresh + incremental vs full refresh + cdc - if a row gets deleted in the source, does incremental remove it?
  - sources: https://olake.io/docs/understanding/terminologies/olake/
  - must: incremental re-reads only rows whose cursor value is greater than the last synced max (primary cursor, optional fallback cursor); deletes are never captured by incremental; updates only if the cursor is something like updated_at (an id cursor only picks new rows); Full Refresh + CDC does an initial full load then streams inserts, updates and deletes from the change log
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/understanding/terminologies/olake/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SYNC-02** [SYNC/answerable/medium/verified=True] whats the diff between cdc and strict_cdc in supported_sync_modes? i dont want to re-copy a 2TB table, only changes from now on
  - sources: https://olake.io/docs/understanding/terminologies/olake/ | https://olake.io/docs/install/docker-cli/ | https://github.com/datazip-inc/olake/blob/master/drivers/abstract/cdc.go | https://github.com/datazip-inc/olake-ui/blob/master/ui/src/modules/ingestion/features/jobs/components/streams/SyncModeSectionView.tsx
  - must: `cdc` = Full Refresh + CDC: initial backfill/snapshot, then change capture; `strict_cdc` = the 'CDC Only' mode: backfill is skipped, only changes after CDC starts are synced; so strict_cdc avoids the re-copy, but existing rows are never loaded into the destination
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/understanding/terminologies/olake/, /docs/install/docker-cli/, gh:olake/blob/master/drivers/abstract/cdc.go, gh:olake-ui/blob/master/ui/src/modules/ingestion/features/jobs/components/streams/SyncModeSectionView.tsx (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 7/7 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Added the UI source that maps the labels: SyncModeSectionView.tsx renders value="cdc" as 'Full Refresh + CDC' and value="strict_cdc" as 'CDC Only' (olake-ui 56826cf). drivers/abstract/cdc.go skips backfill for STRICTCDC ('backfill not enabled'). Caveat worth an answer mentioning: changing the sync mode of an already-syncing stream triggers Clear Destination (terminologies + job-level pages).
- **SYNC-03** [SYNC/answerable/medium/verified=True] running the CLI from a k8s cronjob. how does the next run resume CDC, and what position does the state file keep for postgres vs mysql vs mongo?
  - sources: https://olake.io/docs/install/docker-cli/
  - must: pass `--state /mnt/config/state.json` to `sync`; the state file is created/updated automatically (in the config folder) and must sit on storage that persists between runs; Postgres: global LSN (`global.state.lsn`); MySQL: global binlog file + position (`Name`/`Pos`) plus `server_id`; MongoDB: no global section - per-stream resume token in `state._data`
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/docker-cli/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 8/8 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Code cross-check: protocol/root.go writes state to <config folder>/state.json when --state is empty, and protocol/sync.go reads it only when --state is passed.
- **SYNC-04** [SYNC/answerable/easy/verified=True] if I hit Cancel on a running job, does the next run start from scratch?
  - sources: https://olake.io/docs/getting-started/job-level-properties/
  - must: cancel stops at a safe checkpoint; already-synced data stays in the destination (no rollback); Full Refresh has no state file, so the next run reloads everything; Full Refresh + CDC, Full Refresh + Incremental and Strict CDC keep state and resume; cancellation can take up to ~1 minute
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/getting-started/job-level-properties/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SYNC-05** [SYNC/negative/medium/verified=True] We changed column `price` from INTEGER to TEXT in Postgres. Will OLake change the Iceberg column to string automatically and keep syncing?
  - sources: https://olake.io/docs/features/schema/
  - must: No: writing STRING values into an existing INT/LONG/FLOAT/DOUBLE Iceberg column is unsupported and the sync fails; only widening promotions are applied automatically (e.g. INT->LONG, FLOAT->DOUBLE); INT->STRING is not one of them; the documented 'INT -> STRING handled' case is the opposite direction: numeric values arriving into an existing STRING column are stringified and kept
  - behavior: answer: not supported, cite the support list
  - note: Adversarial re-check 2026-10-16: opened /docs/features/schema/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 7/7 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Softened fact 2 so it no longer requires the full list of promotions, and made fact 3 about the direction trap; the DLQ is no longer required. Code agrees: destination/iceberg/iceberg.go allows only int->long and float->double promotions and rejects other transitions with 'failed to validate schema'. Trap: /docs/core/use-cases/ presents the DLQ as if it exists, while /docs/features/schema/ and /docs/ say 'coming soon'.
- **SYNC-06** [SYNC/answerable/medium/verified=True] added a new column to a postgres table that olake ui is already syncing. will it show up in iceberg, and will the old rows get values?
  - sources: https://olake.io/docs/features/schema/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: schema discovery detects it and adds it to the Iceberg schema when the 'Sync new columns automatically' toggle (on by default) is enabled; otherwise select the column via Edit Streams; existing rows are not backfilled - they stay NULL; to populate old rows run Clear Destination and a full reload (a sparse new column appears only once a non-NULL value arrives)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/features/schema/, /docs/understanding/terminologies/olake/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 7/7 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Removed the CLI key `sync_new_columns` from fact 1: the question is about the UI, and the key appears only on the docker-cli page, which is not a source for this item.
- **SYNC-07** [SYNC/answerable/medium/verified=True] kafka topic gets lots of updates per customer_id and I only want the latest record per customer in iceberg, not every event. how?
  - sources: https://olake.io/docs/connectors/kafka/ | https://olake.io/docs/install/docker-cli/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: switch the stream from the default Append to Upsert and set a Deduplication Key (`dedup_keys`, e.g. ["customer_id"]); Kafka upsert supports positional deletes only: `update_type: "pos"`, `append_mode: false`; needs OLake Go >= 0.12.1 and OLake UI >= 0.7.1; don't increase the topic's partition count while an upsert job runs
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/kafka/, /docs/install/docker-cli/, /docs/understanding/terminologies/olake/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 9/9 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **SYNC-08** [SYNC/answerable/hard/verified=True] why do my mongo collections land in iceberg as a single `data` JSON string column while my postgres tables come out as proper columns? same job settings otherwise
  - sources: https://olake.io/docs/understanding/terminologies/olake/ | https://github.com/datazip-inc/olake/blob/master/drivers/abstract/abstract.go | https://github.com/datazip-inc/olake/blob/master/constants/constants.go
  - must: normalization is on by default only for relational sources (Postgres, MySQL, Oracle, DB2, MSSQL); MongoDB (and S3/Kafka) streams default to normalization off; with normalization off the whole record is stored as a JSON string in the `data` column; turn on Normalization for the stream ("normalization": true) to get level-1 flattening into columns
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/understanding/terminologies/olake/, gh:olake/blob/master/drivers/abstract/abstract.go, gh:olake/blob/master/constants/constants.go (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). The rendered terminologies page also carries the caption 'Query results with normalization off: the data column holds the raw JSON'. constants.go: StringifiedData = "data" and RelationalDrivers = {Postgres, MySQL, Oracle, DB2, MSSQL}. Worth an answer mentioning: switching normalization on for a stream that already synced triggers Clear Destination for that stream (job-level-properties page).
- **SYNC-09** [SYNC/answerable/easy/verified=True] postgres numeric(12,2) money columns land in iceberg as a floating-point column, I expected decimal. bug? can I keep them as decimal?
  - sources: https://olake.io/docs/connectors/postgres/ | https://github.com/datazip-inc/olake/blob/master/drivers/postgres/internal/datatype_conversion.go
  - must: not a bug: OLake has no DECIMAL mapping for Postgres numeric - it is written as a floating-point column per the documented type-mapping table; there is no documented option to keep DECIMAL(p,s) precision in the destination
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/postgres/, gh:olake/blob/master/drivers/postgres/internal/datatype_conversion.go (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 4/4 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). REWROTE. (1) Doc/code drift: the docs table maps numeric -> float, but drivers/postgres/internal/datatype_conversion.go (d20c68e) maps numeric/decimal -> types.Float64, which ToIceberg() turns into Iceberg `double`. The old question's premise ('show up as float') was therefore doubtful and was reworded to 'floating-point'. (2) Dropped the timestamptz/UTC fact (off-topic) and the double-precision fact (tangential). An answer that says float or double should pass.
- **SYNC-10** [SYNC/answerable/easy/verified=True] mysql full refresh fails on one table with `failed to get or split chunks`. ideas?
  - sources: https://olake.io/docs/connectors/mysql/
  - must: cause: the table's statistics are not populated/stale, so the row estimate used for chunking is 0 (the docs also list an empty table as a cause); fix: run `ANALYZE TABLE <namespace>.<table_name>;` then retry
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mysql/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 4/4 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Code cross-check (drivers/mysql/internal/backfill.go, d20c68e): when the information_schema estimate is 0 but the table has rows, the driver fails with 'stats not populated ... Please run ANALYZE TABLE', and abstract/backfill.go wraps that as 'failed to get or split chunks'. A truly empty table is now skipped with a warning, so the docs' 'table contains 0 records' cause looks stale. Fact 1 therefore requires only the statistics cause.
- **SYNC-11** [SYNC/answerable/hard/verified=True] is `initial_wait_time: 10` in our mysql source.json actually honored? we copied it from the docs example
  - sources: https://olake.io/docs/connectors/mysql/ | https://github.com/datazip-inc/olake/blob/master/drivers/mysql/internal/mysql.go
  - must: no: the current MySQL driver enforces a 120-second minimum; anything lower is raised to 120 with a warning in the logs; initial_wait_time is how long the binlog syncer waits (idle) before exiting / while locating the saved position; the docs example value (10) is below the enforced minimum - raise it further if you hit 'Idle Timeout Reached, Exiting Binlog Syncer'
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/connectors/mysql/, gh:olake/blob/master/drivers/mysql/internal/mysql.go (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Since v0.10.0: commit d4088e3 (#1029, 'enforce CDC initial wait time defaults') is contained in tag v0.10.0, and the v0.10.0 release notes mention 'CDC initial wait time validation' without the number. drivers/mysql/resources/spec.json has no minimum (the UI accepts 10), while the Postgres spec sets minimum 120.
- **DST-01** [DST/answerable/easy/verified=True] minimal destination.json for iceberg on aws glue?
  - sources: https://olake.io/docs/writers/iceberg/catalog/glue/
  - must: "type": "ICEBERG" with writer.catalog_type "glue"; required: iceberg_s3_path (s3://bucket/) and aws_region; aws_access_key/secret_key optional when IAM roles are used; for Glue the catalog name is fixed to olake_iceberg; IAM needs Glue table/database actions plus S3 read/write
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/writers/iceberg/catalog/glue/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 8/8 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **DST-02** [DST/answerable/medium/verified=True] iceberg to a local minio with a postgres JDBC catalog - what do I set for s3_endpoint / ssl / path style? connection errors when I use localhost
  - sources: https://olake.io/docs/writers/iceberg/catalog/jdbc/
  - must: catalog_type "jdbc" with jdbc_url, jdbc_username, jdbc_password, plus iceberg_s3_path and aws_region; `s3_endpoint` = the MinIO URL, `s3_path_style: true` (MinIO needs path-style), `s3_use_ssl: false` for an http:// endpoint; from inside Docker use host.docker.internal (or the container name) instead of localhost
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/writers/iceberg/catalog/jdbc/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **DST-03** [DST/answerable/medium/verified=True] can olake write plain parquet into a GCS bucket? how do credentials work there
  - sources: https://olake.io/docs/writers/parquet/config/ | https://olake.io/docs/writers/parquet/gcs/ | https://olake.io/docs/writers/parquet/permission/
  - must: yes - use the Parquet (S3) writer against GCS's S3-compatible API with s3_endpoint `https://storage.googleapis.com`; create HMAC keys for a service account and use them as s3_access_key / s3_secret_key; s3_bucket is the bucket name without gs://; the service account needs storage bucket/object permissions
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/writers/parquet/config/, /docs/writers/parquet/gcs/, /docs/writers/parquet/permission/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Added /docs/writers/parquet/permission/ (in sitemap, HTTP 200): it is the page that lists the GCS custom role's permissions (storage.buckets.get/list, storage.objects.list/get/create/delete/update) that fact 3 relies on.
- **DST-04** [DST/answerable/medium/verified=True] how do we land iceberg tables on azure adls gen2?
  - sources: https://olake.io/docs/writers/iceberg/azure/
  - must: use an Iceberg REST catalog (the guide uses Lakekeeper) with an Azure/ADLS Gen2 warehouse; storage account needs Hierarchical namespace enabled; service principal with Storage Blob Data Owner and Storage Blob Delegator roles; OLake destination: Catalog Type REST, REST Catalog URL, S3 Endpoint `https://<account>.dfs.core.windows.net`, AWS keys left empty
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/writers/iceberg/azure/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 7/7 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **DST-05** [DST/answerable/easy/verified=True] partition an iceberg table by day(created_at) and also bucket user_id - whats the partition_regex syntax?
  - sources: https://olake.io/docs/writers/iceberg/partitioning/
  - must: `"partition_regex": "/{created_at, day}/{user_id, bucket[N]}"` - one /{field, transform} segment per partition level (e.g. bucket[32]); bucket[N] hashes user_id into N buckets (0..N-1); set it per stream: the stream's Partitioning tab in the UI, or `partition_regex` under selected_streams in streams.json (CLI)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/writers/iceberg/partitioning/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 6/6 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Replaced two tangential must-mentions (the full transform list, and the redundant-time-transform warning, which does not apply to day + bucket) with the bucket semantics and where the setting lives.
- **DST-06** [DST/negative/easy/verified=True] can olake write CSV or JSON files to S3 instead of parquet?
  - sources: https://olake.io/docs/writers/parquet/config/ | https://olake.io/docs/
  - must: not supported: destinations are Apache Iceberg tables or Parquet files only; the file writer's `type` only accepts "PARQUET" (files are SNAPPY-compressed)
  - behavior: answer: not supported, cite the support list
  - note: Adversarial re-check 2026-10-16: opened /docs/writers/parquet/config/, /docs/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf).
- **DST-07** [DST/answerable/medium/verified=True] we query the tables with Athena - can we use deletion vectors for upserts? which delete format should we pick?
  - sources: https://olake.io/docs/understanding/compatibility-engines/ | https://olake.io/docs/getting-started/job-level-properties/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: Athena reads equality and positional deletes but not deletion vectors (DVs are the Iceberg v3 format); use equality (default) or positional deletes; select Athena as Target Query Engine so the Streams page only offers compatible upsert types (OLake UI 0.6.0+)
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/understanding/compatibility-engines/, /docs/getting-started/job-level-properties/, /docs/understanding/terminologies/olake/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 5/5 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Added the terminologies page: it states the default-format order (equality, then positional, then deletion vectors; first one the engine supports), which fact 2's '(default)' relies on.
- **DST-08** [DST/answerable/hard/verified=True] we switched upsert type to positional deletes on our helm deployment. anything extra to set up so syncs don't keep rebuilding stuff / failing?
  - sources: https://olake.io/docs/install/kubernetes/ | https://olake.io/docs/understanding/terminologies/olake/
  - must: positional deletes / deletion vectors need a persistent Pebble index; the Helm chart provisions a per-job PVC `olake-index-<JobID>` (configured under `jobIndexes`, default 20Gi, can only grow); every component must be new enough: OLake >= 0.11.0, OLake UI >= 0.6.0, Helm chart >= 0.0.28, worker >= 0.3.11; keep the job pod in the PVC's availability zone (else Pending) - e.g. node affinity via jobProfiles or a single AZ
  - behavior: answer
  - note: Adversarial re-check 2026-10-16: opened /docs/install/kubernetes/, /docs/understanding/terminologies/olake/ (each HTTP 200 at the exact URL; docs URLs match the sitemap's trailing-slash form); 11/11 evidence snippets matched (scratchpad scripts/check_evidence.py; repos olake d20c68e, olake-ui 56826cf). Helm cross-check (olake-helm c63f10c, chart 0.0.30): values.yaml documents the `olake-index-<JobID>` claim, the worker default of 20Gi, and that size is grow-only.
