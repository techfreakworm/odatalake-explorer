---
url: https://github.com/datazip-inc/olake-helm/issues/100
---
- Symptom: the OLake Helm chart hardcoded the olake-ui Service node port to 30082, so a Helm install failed with a port conflict when another application already used that port.
- Fix (maintainer): the chart now supports automatic node port assignment and setting a custom node port in `values.yaml`. No version is named in the thread.
