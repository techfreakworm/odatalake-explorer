---
title: What OLake does not support, or the docs do not document
cite_urls:
  - https://olake.io/docs/
---
# Unsupported or undocumented in OLake
<!-- cite: https://olake.io/docs/ -->

Things people ask about that OLake does not support, or that its docs do not document, with the page that lists what is supported.

## Sources that are not supported
<!-- cite: https://olake.io/docs/ https://olake.io/docs/understanding/compatibility-engines/ -->

- OLake Go reads from eight sources: PostgreSQL, MySQL (and MariaDB), MongoDB, MSSQL (SQL Server), Oracle Database, IBM DB2, Apache Kafka and Amazon S3.
- Any other system is not a supported source, for example Snowflake, Google BigQuery, Amazon DynamoDB, Amazon Redshift, Cassandra or Elasticsearch.
- Snowflake, BigQuery and Redshift appear in the docs as query engines that read the Iceberg tables OLake writes (and Snowflake Horizon and Google BigLake as Iceberg catalogs), not as sources.

## Sync modes that are not supported
<!-- cite: https://olake.io/docs/ https://olake.io/docs/connectors/oracle/ https://olake.io/docs/connectors/db2/ https://olake.io/docs/connectors/s3/ https://olake.io/docs/connectors/kafka/ -->

- CDC (Full Refresh + CDC or CDC Only) is not supported for Oracle, DB2 or S3; they support Full Refresh and Full Refresh + Incremental.
- Kafka supports only CDC Only: no Full Refresh and no Incremental.
- DB2: the IBM Data Server ODBC and CLI driver is not supported on Linux arm64; AMD64 is recommended.

## Destinations that are not supported
<!-- cite: https://olake.io/docs/ -->

- OLake Go writes only Apache Iceberg tables and Parquet files. Other table formats and warehouses (for example Delta Lake, Apache Hudi, or loading straight into Snowflake, BigQuery or ClickHouse tables) are not OLake destinations; query engines read the Iceberg tables OLake writes instead.

## Not available yet
<!-- cite: https://olake.io/docs/ -->

- Dead Letter Queue (DLQ) columns, which would store values with unsupported type changes instead of failing the sync, are marked "Coming soon" on the docs home page.

## OLake Fusion (table maintenance) scope
<!-- cite: https://olake.io/docs/fusion/compaction/types-of-compaction/ https://olake.io/docs/fusion/release/maintenance/v0.1.0/ https://olake.io/docs/fusion/core/use-cases/ -->

- OLake Fusion's documented maintenance is compaction (Lite, Medium and Full) plus table observability (file metrics and a health score).
- Snapshot expiry: the Fusion v0.1.0 to v0.1.4 release notes say automatic snapshot expiry was disabled, to keep snapshots from being removed automatically.
- Orphan-file cleanup: not documented for OLake Fusion.

## Login, security and commercial terms
<!-- cite: https://olake.io/docs/install/kubernetes/ https://olake.io/olake-go/ https://olake.io/olake-fusion/ -->

- Single sign-on (SSO, SAML, LDAP or OIDC login) for the OLake UI is not documented.
- On Kubernetes, OLake does not support setting a `securityContext` for the `nfsServer`.
- Pricing, SLAs and enterprise plans are not published. The OLake Go FAQ says enterprise support is in the works and points to hello@olake.io, and that OLake Go is open source under the Apache 2.0 license. The OLake Fusion FAQ says Fusion is open source and you pay only for the compute and storage you provision.
