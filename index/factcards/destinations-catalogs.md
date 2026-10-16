---
title: OLake Go destinations, Iceberg catalogs and their minimum versions
cite_urls:
  - https://olake.io/docs/understanding/compatibility-catalogs/
---
# OLake Go destinations and Iceberg catalogs
<!-- cite: https://olake.io/docs/ https://olake.io/docs/understanding/compatibility-catalogs/ -->

OLake Go writes to two kinds of destination:

- Apache Iceberg tables, registered in an Iceberg catalog, with data and metadata files on object storage.
- Parquet files on object storage (Amazon S3, MinIO, Google Cloud Storage) or on a local path.

## Supported Iceberg catalogs
<!-- cite: https://olake.io/docs/understanding/compatibility-catalogs/ https://olake.io/docs/writers/iceberg/catalog/rest/ -->

The catalog compatibility page lists 11 Iceberg catalogs. The minimum OLake Go version is the one the setup page states; "not stated" means the docs give none.

| Catalog | Setup guide | Minimum OLake Go version |
|---|---|---|
| AWS Glue | Glue catalog page | not stated |
| REST (Generic) | REST catalog page | not stated |
| REST Lakekeeper | REST catalog page | not stated |
| REST Nessie | REST catalog page | not stated |
| REST Apache Polaris | REST catalog page | not stated |
| REST Unity (Databricks Unity Catalog) | REST catalog page | not stated |
| S3 Tables | REST catalog page | not stated |
| REST BigLake (Google) | REST catalog page | 0.9.1 and above |
| REST Horizon (Snowflake Horizon Catalog) | REST catalog page | 0.11.0 and above |
| JDBC | JDBC catalog page | not stated |
| Hive Metastore | Hive catalog page | not stated |

- A custom catalog name is supported from v0.3.5; it may contain only lowercase letters and underscores (no spaces or special characters).

## Storage behind each catalog
<!-- cite: https://olake.io/docs/writers/iceberg/catalog/glue/ https://olake.io/docs/writers/iceberg/catalog/hive/ https://olake.io/docs/writers/iceberg/catalog/jdbc/ https://olake.io/docs/writers/iceberg/azure/ https://olake.io/docs/writers/iceberg/gcp/ -->

- AWS Glue: data and metadata files in Amazon S3, metadata managed by the Glue Data Catalog; the S3 bucket should be in the same AWS region as the Glue catalog.
- Hive Metastore: object storage such as S3, GCS, MinIO or another S3-compatible system.
- JDBC catalog: a relational database such as PostgreSQL or MySQL holds the Iceberg metadata; data goes to S3, MinIO or another S3-compatible store.
- Azure: Iceberg on Azure Data Lake Storage (ADLS) Gen2 is documented with the Lakekeeper REST catalog.
- Google Cloud Storage: Iceberg on GCS is documented with the Hive catalog.

## When each catalog arrived (release notes)
<!-- cite: https://olake.io/docs/release/ingestion/28-04-2025/ https://olake.io/docs/release/ingestion/v0.1.2-v0.1.5/ https://olake.io/docs/release/ingestion/v0.9.0/ https://olake.io/docs/release/ingestion/v0.11.0/ https://olake.io/docs/release/ingestion/v0.3.5/ https://olake.io/docs/writers/iceberg/catalog/rest/ -->

- Hive catalog support: the 28-04-2025 release (which also renamed `catalog.json` to `streams.json`).
- Databricks Unity Catalog support: the v0.1.2 to v0.1.5 releases (June 26 to July 1, 2025).
- Custom catalog name: v0.3.5.
- Google BigLake catalog support (and BigLake multi-bucket catalogs): listed in the v0.9.0 release notes, while the REST catalog page says BigLake needs v0.9.1 and above.
- Snowflake Horizon Catalog support: v0.11.0.

## Parquet destination
<!-- cite: https://olake.io/docs/writers/parquet/config/ https://olake.io/docs/writers/parquet/gcs/ https://olake.io/docs/writers/parquet/local/ -->

- S3 Parquet writes Parquet files directly to an S3 bucket (AWS S3 or MinIO); Google Cloud Storage works through its S3-compatible API with HMAC keys used as the access key and secret key.
- The local Parquet writer writes to a local path (`local_path`, for example `/mnt/config` with Docker).
