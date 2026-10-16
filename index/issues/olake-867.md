---
url: https://github.com/datazip-inc/olake/issues/867
fixed_in: v0.6.0
---
- Symptom: Oracle to Iceberg incremental sync with a `TIMESTAMP` cursor column (no time zone) did not pick up new or updated rows after the first run: zero rows ingested, no new Iceberg snapshot, no new Parquet files, and `state.json` unchanged across runs. Reported on OLake 0.5.0 (Helm chart 0.0.14, Oracle 19c, database time zone +02:00).
- `TIMESTAMP WITH TIME ZONE` and `TIMESTAMP WITH LOCAL TIME ZONE` cursor columns worked as expected.
- A maintainer released the fix in OLake v0.6.0; the reporter confirmed that 0.6.4 picks up new rows in incremental syncs.
- Also from the thread: source and destination connector versions are never updated automatically, so pick the new connector version for the source; on Kubernetes, pin image tags in the Helm values together with `pullPolicy: IfNotPresent` to avoid unintended upgrades.
