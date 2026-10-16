---
title: Known contradictions between OLake pages
cite_urls:
  - https://olake.io/docs/fusion/getting-started/configure-first-compaction/
---
# Known contradictions between OLake pages
<!-- cite: https://olake.io/docs/fusion/getting-started/configure-first-compaction/ -->

Places where two first-party OLake pages disagree. When answering, cite both pages and say they differ.

## OLake Fusion default compaction schedule
<!-- cite: https://olake.io/docs/fusion/getting-started/configure-first-compaction/ https://olake.io/docs/fusion/compaction/configuration/ https://olake.io/olake-fusion/ -->

- The "Configure your first compaction" page says default schedules are applied automatically: Lite every 1 hour, Medium every 8 hours, Full never (not scheduled).
- The compaction configuration page says that if a configuration is left unset (for example in Bulk Configure), the defaults are 24 hours for each compaction type and a 512 MB target file size.
- The OLake Fusion product FAQ quotes Lite every 20 minutes and Medium every 40 minutes, but as the cadence used in a benchmark, not as defaults.
- Both docs pages give 512 MB as the default target file size (the FAQ's benchmark also used 512 MB).

## MySQL `binlog_row_metadata=FULL`
<!-- cite: https://olake.io/docs/connectors/mysql/ https://olake.io/docs/release/ingestion/v0.10.0/ -->

- The MySQL connector page lists `binlog_row_metadata=FULL` under the required binary logging settings for CDC.
- The v0.10.0 release notes say MySQL CDC works without `binlog_row_metadata=FULL`, for MySQL and MariaDB setups where full row metadata is unavailable.

## MySQL `initial_wait_time` examples
<!-- cite: https://olake.io/docs/connectors/mysql/ https://olake.io/docs/connectors/mysql/setup/local/ -->

- On the MySQL connector page, the example `source.json` and the field table use `"initial_wait_time": 10`, while the `update_method` row of the same table shows `{"initial_wait_time": 120}`; the local setup page's example uses 1.
- `initial_wait_time` is the maximum time in seconds to wait before the binlog syncer is considered idle; the troubleshooting section says to raise it when locating the saved binlog position takes longer than the configured value.

## Google BigLake catalog version
<!-- cite: https://olake.io/docs/writers/iceberg/catalog/rest/ https://olake.io/docs/release/ingestion/v0.9.0/ -->

- The REST catalog page says BigLake catalog support is available in OLake Go 0.9.1 and above.
- The v0.9.0 release notes already list Google BigLake catalog support (with the Iceberg upgrade to 1.10.2).
