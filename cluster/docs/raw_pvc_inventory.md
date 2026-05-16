# Raw PVC Inventory

PVCs not managed by a database operator (CNPG, Valkey/Redis operator). All are
single-pod SPOFs with no replication or operator-managed failover.

Last updated: 2026-05-15

| PVC                                        | Size  | StorageClass           | What it holds                        |
| ------------------------------------------ | ----- | ---------------------- | ------------------------------------ |
| `arc-runners/cache-github-runner-0`        | 50Gi  | local-path             | GitHub Actions runner cache          |
| `cpap-sync/cpap-data`                      | 50Gi  | lvm-proxmox-hdd-shared | CPAP sync data                       |
| `gatus/gatus`                              | 200Mi | local-path             | Gatus status check DB (SQLite)       |
| `grocy-sf/grocy-config`                    | 1Gi   | local-path-hetzner     | Grocy SF app data (SQLite + uploads) |
| `grocy-vallejo/grocy-config`               | 1Gi   | local-path-hetzner     | Grocy Vallejo app data               |
| `harbor/harbor-registry`                   | 30Gi  | lvm-proxmox-hdd        | Container image blobs                |
| `harbor/harbor-jobservice`                 | 1Gi   | lvm-proxmox-hdd        | Harbor job logs                      |
| `loki/storage-loki-0`                      | 10Gi  | local-path-hetzner     | Loki log chunks                      |
| `matrix/matrix-synapse`                    | 20Gi  | local-path-proxmox     | Synapse media + state                |
| `minio-hil/export-minio-0`                 | 40Gi  | local-path             | MinIO object storage                 |
| `minio-hil/export-minio-1`                 | 40Gi  | local-path             | MinIO object storage                 |
| `minio-hil/export-minio-2`                 | 40Gi  | local-path             | MinIO object storage                 |
| `minio-hil/export-minio-3`                 | 40Gi  | local-path             | MinIO object storage                 |
| `monitoring/db-alertmanager-monitoring-0`  | 1Gi   | local-path-hetzner     | Mimir alertmanager state             |
| `monitoring/db-alertmanager-monitoring-1`  | 1Gi   | local-path-hetzner     | Mimir alertmanager state             |
| `monitoring/storage-mimir-compactor-0`     | 10Gi  | local-path-hetzner     | Mimir TSDB blocks                    |
| `monitoring/storage-mimir-ingester-0`      | 10Gi  | local-path-hetzner     | Mimir TSDB blocks                    |
| `monitoring/storage-mimir-store-gateway-0` | 10Gi  | local-path-hetzner     | Mimir TSDB blocks                    |
| `nix-cache/attic-cache`                    | 30Gi  | local-path             | Nix binary cache store               |
| `ollama/llm-models`                        | 200Gi | lvm-proxmox-hdd        | LLM model weights                    |
| `openhands/openhands-data`                 | 10Gi  | local-path-proxmox     | OpenHands workspace data             |
| `study-casino/study-casino-data`           | 10Gi  | hcloud-volumes         | Study casino data                    |
| `tana-mcp/tana-mcp-config`                 | 10Gi  | hcloud-volumes         | Tana MCP state                       |
| `thrive-scraper/thrive-data`               | 10Gi  | lvm-proxmox-hdd-shared | Thrive scraper data                  |
| `tofu-state/tofu-state-backup`             | 1Gi   | local-path-proxmox     | tofu state backups                   |
