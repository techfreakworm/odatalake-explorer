---
url: https://github.com/datazip-inc/olake/issues/877
fixed_in: v0.6.1
---
- Symptom: after adding a new stream to a job, OLake runs "Clear Destination" for it; when that call fails (here an S3 destination pointed at Google Cloud Storage, which returns `NotImplemented` for `DeleteObjects`), the job stays in "InProgress" forever.
- By design, clear-destination is a destructive operation that retries indefinitely instead of stopping half-applied.
- Recovery while the problem exists: an internal API cancels the in-progress clear and resumes the sync: `POST /internal/project/123/jobs/<JOB_ID>/clear-destination/recover` on the OLake UI server, after logging in. If data for the affected stream is already in the destination, drop it manually first.
- Clearing all streams can be restarted from the job settings; there is no retry for clearing only some streams.
- Fix: OLake v0.6.1 added a fallback for S3-compatible backends that return `NotImplemented` for `DeleteObjects`; the issue was closed as solved in v0.6.1.
