---
title: OLake Go sources and the sync modes each one supports
cite_urls:
  - https://olake.io/docs/
---
# OLake Go sources and their sync modes
<!-- cite: https://olake.io/docs/ https://olake.io/docs/understanding/terminologies/olake/ -->

The sources OLake Go (the ingestion product) can read from, with the sync modes each one supports. Every source supports Full Refresh + Incremental except Kafka.

| Source | Full Refresh | Full Refresh + Incremental | Full Refresh + CDC | CDC Only (Strict CDC) |
|---|---|---|---|---|
| PostgreSQL | yes | yes | yes | yes |
| MySQL (the MySQL connector also covers MariaDB) | yes | yes | yes | yes |
| MongoDB | yes | yes | yes | yes |
| MSSQL (SQL Server) | yes | yes | yes | yes |
| Oracle Database | yes | yes | no | no |
| IBM DB2 | yes | yes | no | no |
| Apache Kafka | no | no | no | yes (its only mode) |
| Amazon S3 and S3-compatible storage | yes | yes | no | no |

- No CDC for Oracle, DB2 or S3: neither Full Refresh + CDC nor CDC Only is supported for them; use Full Refresh or Full Refresh + Incremental.
- Kafka supports only one sync mode: CDC Only. Full Refresh and Incremental are not available for Kafka.

## Sync mode names
<!-- cite: https://olake.io/docs/understanding/terminologies/olake/ https://olake.io/docs/install/docker-cli/ https://olake.io/docs/getting-started/job-level-properties/ -->

- Full Refresh: copies the whole table every run (`full_refresh` in streams.json); it keeps no state file.
- Full Refresh + Incremental: a full refresh first, then only rows whose cursor field is greater than the last synced value (`incremental`). An auto-increment cursor picks up new rows only; an `updated_at`-style cursor also picks up updates; deletes are never tracked.
- Full Refresh + CDC: a full refresh first, then inserts, updates and deletes from the change stream (`cdc`).
- CDC Only, also called Strict CDC (`strict_cdc`): skips the full refresh and processes only changes after CDC begins.
- Changing a stream's sync mode triggers Clear Destination.

## PostgreSQL
<!-- cite: https://olake.io/docs/connectors/postgres/ https://olake.io/docs/ -->

- Sync modes: Full Refresh, Full Refresh + Incremental, Full Refresh + CDC and CDC Only.
- Requires PostgreSQL 10 or above. CDC uses the native `pgoutput` plugin; the `wal2json`-based CDC method is deprecated.

## MySQL and MariaDB
<!-- cite: https://olake.io/docs/connectors/mysql/ https://olake.io/docs/ https://olake.io/docs/release/ingestion/v0.10.0/ -->

- Sync modes: Full Refresh, Full Refresh + Incremental, Full Refresh + CDC and CDC Only.
- The MySQL connector also supports MariaDB as a CDC source.
- Requires MySQL 5.7+. CDC reads the binary log: the MySQL page lists `log_bin=ON`, `binlog_format=ROW`, `binlog_row_image=FULL` and `binlog_row_metadata=FULL` as required, a unique `server-id`, and the REPLICATION SLAVE, REPLICATION CLIENT and SELECT privileges.
- The v0.10.0 release notes add MySQL CDC without `binlog_row_metadata=FULL`, for MySQL and MariaDB setups where full row metadata is unavailable, so the two pages disagree on whether that setting is required.

## MongoDB
<!-- cite: https://olake.io/docs/connectors/mongodb/ https://olake.io/docs/ -->

- Sync modes: Full Refresh, Full Refresh + Incremental, Full Refresh + CDC and CDC Only.
- Requires MongoDB 4.0 or higher. CDC requires replica set mode (`--replSet`) with the oplog; without it, use Incremental sync.
- CDC is not a continuous always-on process: each CDC sync runs through the orchestrator (a job run).

## MSSQL (SQL Server)
<!-- cite: https://olake.io/docs/connectors/mssql/ https://olake.io/docs/ -->

- Sync modes: Full Refresh, Full Refresh + Incremental, Full Refresh + CDC and CDC Only.
- Requires SQL Server 2017 or higher. CDC must be enabled on the database and on each table to capture; CDC change tables keep events for 3 days by default, and expired events require a full backfill.

## Oracle
<!-- cite: https://olake.io/docs/connectors/oracle/ https://olake.io/docs/ -->

- Sync modes: Full Refresh and Full Refresh + Incremental only. Oracle has no CDC support in OLake Go: neither Full Refresh + CDC nor CDC Only is available.
- Requires Oracle Database 11g or above (tested with 19c and 23ai); the user needs CREATE SESSION and SELECT on the tables.

## IBM DB2
<!-- cite: https://olake.io/docs/connectors/db2/ https://olake.io/docs/ -->

- Sync modes: Full Refresh and Full Refresh + Incremental only; no CDC.
- Requires DB2 11.5.3 or higher. The IBM Data Server ODBC and CLI driver is not supported on Linux arm64; AMD64 is the recommended CPU architecture.

## Apache Kafka
<!-- cite: https://olake.io/docs/connectors/kafka/ https://olake.io/docs/ https://olake.io/docs/understanding/terminologies/olake/ -->

- Sync mode: CDC Only, the only mode the Kafka connector supports (no Full Refresh, no Incremental).
- Requires Kafka 2.4.0 or higher; Kafka as a source is available from OLake Go v0.3.0; tested with Amazon MSK.
- Messages must be JSON or Avro (Avro needs a Confluent Schema Registry). Messages already past the topic's retention period cannot be synced.
- Ingestion mode defaults to Append for Kafka. Upsert needs a deduplication key, uses positional deletes only, and requires OLake Go 0.12.1+ and OLake UI 0.7.1+.

## Amazon S3
<!-- cite: https://olake.io/docs/connectors/s3/ https://olake.io/docs/ -->

- Sync modes: Full Refresh and Full Refresh + Incremental only; no CDC.
- Incremental sync uses each file's S3 `LastModified` timestamp as the cursor (`_last_modified_time`); a file that is modified and re-uploaded is synced again.
- Formats: CSV, JSON (JSONL and array), XML and Parquet, with transparent gzip decompression; works with AWS S3 and S3-compatible services (MinIO, LocalStack).
