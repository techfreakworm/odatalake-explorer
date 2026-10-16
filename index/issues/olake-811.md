---
url: https://github.com/datazip-inc/olake/issues/811#issuecomment-3895500238
fixed_in: the MySQL source driver v0.3.16
---
- Symptom: with a MySQL server whose time zone is not UTC (for example `US/Eastern`), a `TIMESTAMP` column was written with different values by the initial load and by CDC: the full load respected the server time zone, CDC wrote the value as UTC.
- A maintainer said the fix shipped in the MySQL driver v0.3.16, and that existing jobs keep the old behaviour for backward compatibility.
- Why the fix may not take effect (the linked comment): a state file created by an older version stays on `"version": 1`, so the fix is not applied while that state file is passed.
- Steps from the linked comment: 1) run `clear-destination` (it removes the existing data from the destination); 2) run the next sync without the state file, which writes a new state file with `"version": 2`; then pass the state file again for later syncs.
- Later in the thread: run the first sync after `discover` without the `--state` flag so the state is created with the latest version; OLake UI users should update the worker to the latest version.
