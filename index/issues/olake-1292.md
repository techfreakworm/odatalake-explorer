---
url: https://github.com/datazip-inc/olake/issues/1292
fixed_in: v0.12.1
---
- Symptom: MySQL-connector CDC from MariaDB (reported on Amazon RDS for MariaDB 10.11) failed permanently with `ERROR 1236: Failed to replace GTID event with backwards-compatible event: corrupt event`; every retry resumed from the saved binlog position and failed on the same event.
- Cause: the binlog syncer always registered with the `mysql` flavor, so MariaDB treated OLake as a legacy replica without GTID support and rewrote GTID events; the rewrite failed on a GTID event that carries a group-commit id. On RDS the event can come from RDS housekeeping transactions.
- Impact: the only manual workaround (moving the saved position past the event) skips the changes in between; if a job stays stuck longer than the binlog retention, a full resync is needed.
- Fix: PR #1307 passes the detected server flavor to the binlog syncer, so MariaDB sources register with GTID capability; maintainers merged it and released the fix in v0.12.1.
