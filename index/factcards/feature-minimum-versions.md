---
title: OLake features and the minimum component versions they need
cite_urls:
  - https://olake.io/docs/understanding/terminologies/olake/
---
# Feature to minimum component versions
<!-- cite: https://olake.io/docs/understanding/terminologies/olake/ -->

OLake has several separately versioned components: the OLake Go connectors (also called the OLake version or driver version), the OLake UI, the OLake worker and the Helm chart. Some features need minimum versions of several of them at once; upgrading only one component can make sync jobs fail.

## Delete formats (Upsert types) and the index DB
<!-- cite: https://olake.io/docs/understanding/terminologies/olake/ https://olake.io/docs/install/olake-ui/ https://olake.io/docs/install/kubernetes/ -->

- Choosing the Iceberg delete format (equality deletes, positional deletes or deletion vectors) needs OLake 0.11.0+, OLake UI 0.6.0+, Helm chart 0.0.28+ and OLake worker 0.3.11+.
- Positional deletes and deletion vectors need a persistent index store (a local Pebble DB, configured with `OLAKE_INDEX_DB_DIR`, `OLAKE_INDEX_DB_CACHE_SIZE` and `OLAKE_INDEX_DB_MAX_OPEN_FILES` on the temporal-worker); equality deletes, the default, need no index DB.
- Deletion vectors are Iceberg v3; equality and positional deletes are Iceberg v2. Switching between deletion vectors and equality or positional deletes on an existing job triggers Clear Destination.

## Kafka
<!-- cite: https://olake.io/docs/connectors/kafka/ -->

- Kafka as a source: OLake Go v0.3.0 and above.
- Kafka Upsert ingestion mode: OLake Go 0.12.1 and above with OLake UI 0.7.1 and above.

## Log storage on S3
<!-- cite: https://olake.io/docs/install/kubernetes/ https://olake.io/docs/install/olake-ui/ -->

- Storing job logs on S3 instead of NFS needs OLake 0.12.0+, OLake UI 0.7.0+, OLake worker 0.4.0+ and, on Kubernetes, Helm chart 0.0.30+.
- On Kubernetes, NFS is still the default log storage mode but is deprecated, to be removed at the end of 2026, when S3 becomes the default.

## OLake Fusion (Iceberg maintenance)
<!-- cite: https://olake.io/docs/fusion/getting-started/overview/ https://olake.io/docs/fusion/getting-started/configure-first-compaction/ -->

- The Maintenance module (OLake Fusion inside the OLake UI) is available from OLake UI v0.4.0.
- For conflict-free compaction of OLake-ingested tables, the OLake Go (ingestion) driver must be v0.7.0 or higher.

## UI, alerts and monitoring
<!-- cite: https://olake.io/docs/getting-started/alerts-and-notifications/ https://olake.io/docs/getting-started/job-level-properties/ https://olake.io/docs/monitoring-and-observability/metrics/ -->

- Alerts and notifications: OLake UI 0.2.3+ and worker 0.2.3+.
- Target Query Engine (a job setting): OLake UI 0.6.0 and above.
- Clear Destination: stable from OLake Go v0.3.0.
- The `/metrics` endpoint: OLake UI 0.5.0 or higher; the `olake_sync_bytes_read`, `olake_process_cpu_usage_ratio` and `olake_process_memory_usage_bytes` metrics need OLake Go v0.9.0 or later.

## Streams, filters and columns
<!-- cite: https://olake.io/docs/understanding/terminologies/olake/ https://olake.io/docs/understanding/terminologies/general/ https://olake.io/docs/connectors/mysql/ -->

- Data filter during CDC and Incremental syncs: OLake Go connector v0.6.0 and OLake UI v0.4.1; it only works for jobs created on connector v0.6.0 or later.
- Column selection and automatic sync of new columns: OLake Go v0.4.0 and OLake UI v0.3.1.
- Source Naming Convention: OLake Go v0.7.7 and OLake UI v0.4.7.
- Driver-specific CDC metadata columns (for example `_cdc_lsn` for Postgres, `_cdc_binlog_file_name` and `_cdc_binlog_file_pos` for MySQL, `_cdc_start_lsn` and `_cdc_seqval` for MSSQL): the docs say the feature is available starting from v0.3.16.
- MySQL `INT UNSIGNED` maps to `bigint` from OLake Go 0.4.1 (to `int` before).

## Catalogs and Helm
<!-- cite: https://olake.io/docs/writers/iceberg/catalog/rest/ https://olake.io/docs/install/kubernetes/ -->

- Google BigLake catalog: OLake Go 0.9.1 and above. Snowflake Horizon catalog: OLake Go 0.11.0 and above. Custom catalog names: v0.3.5 and above.
- From Helm chart 0.0.11, the chart disables Elasticsearch by default and uses PostgreSQL for both metadata and Temporal visibility.
