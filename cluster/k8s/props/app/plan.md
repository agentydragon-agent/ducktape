# Props cluster deployment — TODOs

## Langfuse

- [ ] **TODO(reliability): Move PostgreSQL to hcloud-volumes on VPS** —
      Currently Langfuse's PostgreSQL is on `proxmox-csi-retain`. For
      durability and cross-node HA, move to `hcloud-volumes` on VPS nodes
      (same pattern as Authentik). See `cluster/k8s/langfuse/helmrelease.yaml`.

- [ ] **TODO(reliability): ClickHouse replication** — Currently single-node on
      Proxmox. For production use, deploy a 3-node ClickHouse cluster.
      See `cluster/k8s/langfuse/helmrelease.yaml`.

- [ ] **TODO(reliability): Replace bundled MinIO with external S3** —
      Currently using the Langfuse Helm chart's bundled single-node MinIO on
      Proxmox. For durability, replace with Cloudflare R2, Hetzner Object
      Storage, or a multi-node MinIO cluster.
      See `cluster/k8s/langfuse/helmrelease.yaml`.

- [ ] **TODO(reliability): Move Redis to VPS or add Sentinel** — Currently
      single-node Redis on Proxmox. For reliability add Redis Sentinel or
      move to VPS. See `cluster/k8s/langfuse/helmrelease.yaml`.
