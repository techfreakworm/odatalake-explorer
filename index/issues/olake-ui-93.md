---
url: https://github.com/datazip-inc/olake-ui/issues/93
---
- Symptom: when the temporal-worker crashed, the sync container it had started kept running (an orphaned container still writing to Iceberg), and a Temporal retry could start a second container for the same job, so two processes could write to the same destination and duplicate data.
- Fix: heartbeating was added to the OLake workers. No version is named in the thread.
