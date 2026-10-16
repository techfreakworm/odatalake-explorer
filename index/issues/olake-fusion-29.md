---
url: https://github.com/datazip-inc/olake-fusion/issues/29
---
- Symptom: by default OLake Fusion did not plan all partitions of an Iceberg table in a single optimization (compaction) run.
- Goal of the fix: plan all partitions by default, so no equality deletes are left after any Lite, Medium or Full compaction (as long as no ingestion adds equality deletes after the snapshot the compaction started from).
- Status: closed with PR #26; no version is named in the thread.
