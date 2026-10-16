---
url: https://github.com/datazip-inc/olake/issues/955
---
- Symptom: on Kubernetes (Helm), pressing "Cancel run" in the OLake UI during a MySQL (Aurora) initial load did not stop the sync; queries kept running on the database.
- How cancel works (maintainer): a job is a Temporal workflow; "Cancel run" sends a cancellation request to the workflow, and when the workflow context is cancelled all of its database connections are closed.
- Known limitation of the MySQL driver: a query that is already executing may not stop immediately; it stops when the current scan finishes, which can take longer on a table without a primary key.
- The maintainers could not reproduce the rest of the report and closed the issue for inactivity; no fix version is named.
