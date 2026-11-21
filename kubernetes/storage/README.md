# K3s local-path storage on the academic root volume

The three application PVCs request the K3s bundled `local-path` StorageClass:

- `platform/backend-alert-data` (5 GiB)
- `monitoring/prometheus-data` (10 GiB)
- `monitoring/grafana-data` (2 GiB)

The academic EC2 design does not attach a separate K3s data volume. The K3s
cloud-init configuration sets `default-local-storage-path` to
`/var/lib/rancher/k3s/storage`, which resides on the encrypted gp3 root EBS
volume. No additional StorageClass or provisioner is created.

Local-path claims remain tied to this single node. They survive pod/container
restarts and reboots while the instance and root disk remain, but they do not
provide multi-node failover. The root disk is configured with
`delete_on_termination = true`; terminating the EC2 instance deletes its local
PVC data unless it has been backed up. The PVC requested sizes are not
filesystem quotas, so monitor free space. Maintain and test EBS snapshots and
application-consistent backups, especially for SQLite alert history.

The existing Docker named volumes are separate from Kubernetes PVCs. No Docker
data is imported automatically. Select the authoritative SQLite database,
create and verify a consistent backup, and complete a separately reviewed
one-time migration before the backend first starts against its Kubernetes
claim.
