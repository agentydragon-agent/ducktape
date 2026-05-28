# Props cluster deployment — TODOs

## Langfuse

- [ ] **TODO(reliability): Move PostgreSQL to durable replicated storage** —
      Currently Langfuse's PostgreSQL is on `proxmox-csi-retain`. For
      durability and cross-node HA, use a CNPG-style replicated database on the
      current OVH/Proxmox storage classes. See
      `cluster/k8s/langfuse/helmrelease.yaml`.

- [ ] **TODO(reliability): ClickHouse replication** — Currently single-node on
      Proxmox. For production use, deploy a 3-node ClickHouse cluster.
      See `cluster/k8s/langfuse/helmrelease.yaml`.

- [ ] **TODO(reliability): Replace bundled MinIO with SeaweedFS S3** —
      Currently using the Langfuse Helm chart's bundled single-node MinIO on
      Proxmox. Point Langfuse at the cluster's SeaweedFS S3 gateway
      (`seaweedfs-s3.seaweedfs.svc:8333`, OVH-backed) — same migration pattern
      already applied to Loki, Tempo, and Mimir.
      See `cluster/k8s/langfuse/helmrelease.yaml`.

- [ ] **TODO(reliability): Move Redis to OVH or add Sentinel** — Currently
      single-node Redis on Proxmox. For reliability add Redis Sentinel or
      move to OVH. See `cluster/k8s/langfuse/helmrelease.yaml`.
