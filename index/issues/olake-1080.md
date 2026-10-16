---
url: https://github.com/datazip-inc/olake/issues/1080
fixed_in: v0.9.2
---
- Symptom: setting `tlsCAFile` or `tlsCertificateKeyFile` in the MongoDB source's additional connection parameters fails with `open /certs/root-ca.crt: no such file or directory`, so a self-hosted MongoDB with a private CA or X.509 client certificates could not be reached.
- Cause: the connector does not run inside the temporal-worker. The worker starts a separate short-lived container for each check, discover and sync, and that container only mounts the per-workflow config directory (`/mnt/config`); volumes mounted on the worker are not passed on.
- Fix: OLake v0.9.2 added TLS support for MongoDB: provide the certificate content directly in the MongoDB source configuration, as for other connectors, instead of a file path.
