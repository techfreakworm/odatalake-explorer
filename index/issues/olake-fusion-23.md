---
url: https://github.com/datazip-inc/olake-fusion/issues/23
---
- Symptom: the built-in Prometheus metrics exporter of OLake Fusion did not work: the `olakego/fusion` image had no `plugin/` directory, so `prometheus-reporter.jar` was missing when the `metricReporters` plugin was configured.
- Status: closed after the reporter confirmed the fix; no version is named in the thread.
