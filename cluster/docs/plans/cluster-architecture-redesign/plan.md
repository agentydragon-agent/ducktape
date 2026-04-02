# Cluster Architecture Redesign

Status: **Draft / In Progress**

See also: <sso.md>, <storage.md>

## Motivation

etcd on VPS control planes gets starved by co-scheduled workloads, causing
cluster instability and painful recovery. Redesign node roles and workload
placement to prevent this.

## Current Topology

| Node                  | Role        | Location                      | Specs                      |
| --------------------- | ----------- | ----------------------------- | -------------------------- |
| vps0 (talos-vps-cp-0) | CP (pure)   | Hetzner CPX31 (4 vCPU / 8 GB) | Hillsboro OR               |
| vps1 (talos-vps-cp-1) | CP (pure)   | Hetzner CPX31 (4 vCPU / 8 GB) | Hillsboro OR               |
| talos-vps-worker-0    | Worker      | Hetzner CPX31 (4 vCPU / 8 GB) | Nebula 10.42.0.11          |
| talos-vps-worker-1    | Worker      | Hetzner CPX31 (4 vCPU / 8 GB) | Nebula 10.42.0.12          |
| talos-pve-cp-0        | CP + worker | Proxmox (atlas)               | Private 10.2.1.1           |
| wyrm2                 | Worker      | Proxmox (atlas), NixOS        | 2x RTX 5090, GPU workloads |

VPS workers are also Nebula lighthouses + relays for mesh redundancy.
All CPX31 nodes are grandfathered — CPX31 is no longer available at HIL.

vps0/vps1 are pure CPs (rebuilt, no workloads). VPS workers handle
workloads that need public IP / always-on.

### VPS Sizing

| Role        | Type  | Cores    | RAM  | Disk   | USD/mo    |
| ----------- | ----- | -------- | ---- | ------ | --------- |
| CP (x2)     | CPX31 | 4 shared | 8 GB | 160 GB | 24.99     |
| Worker (x2) | CPX31 | 4 shared | 8 GB | 160 GB | 24.99     |
| **Total**   |       | 16       | 32GB | 640 GB | **99.96** |

#### VPS CP Load (2026-04-01 snapshot)

| Node | CPU actual | MEM actual    | MEM req | MEM lim |
| ---- | ---------- | ------------- | ------- | ------- |
| vps0 | 818m (20%) | 4586 Mi (64%) | 2070 Mi | 6309 Mi |
| vps1 | 942m (23%) | 5169 Mi (72%) | 1998 Mi | 6842 Mi |

**Memory is the bottleneck**, not CPU. Gap is etcd, kube-apiserver, and
Longhorn sidecars (many pods with no resource requests).

### Hetzner HIL Availability (checked 2026-04-01)

CPX31/41/51 no longer available at HIL for new provisioning. Existing
nodes are grandfathered. In-place resize via `hcloud` provider is
possible (`keep_disk = true`, brief downtime per node).

| Server    | vCPU | RAM   | Type            | EUR/mo | Available |
| --------- | ---- | ----- | --------------- | ------ | --------- |
| CPX11     | 2    | 2 GB  | Shared (AMD)    | 4.49   | Yes       |
| CPX21     | 3    | 4 GB  | Shared (AMD)    | 8.99   | Yes       |
| CPX31     | 4    | 8 GB  | Shared (AMD)    | 15.99  | **No**    |
| **CCX13** | 2    | 8 GB  | Dedicated (AMD) | 12.99  | Yes       |
| CCX23     | 4    | 16 GB | Dedicated (AMD) | 25.99  | Yes       |

## Placement Decisions

### VPS-Only Resilience (hard invariant)

If Proxmox (home lab) goes down entirely, the following **must still
work** using only VPS nodes:

- **Nebula mesh** (lighthouses + relays on VPS)
- **Website** (`allegedly.works`)
- **DNS** (PowerDNS, authoritative)
- **Gateway/Ingress** (public HTTPS)

Additionally: **Proxmox going down must not destabilize VPS.** Enforce
via hard `nodeSelector` on Proxmox workloads and PriorityClasses for
VPS-critical services.

### Hard Constraints (Decided)

| Service         | Where               | Reason                                                 |
| --------------- | ------------------- | ------------------------------------------------------ |
| Ollama          | Proxmox (wyrm2)     | GPU-bound (2x RTX 5090)                                |
| LiteLLM         | Proxmox             | Colocate with Ollama                                   |
| PowerDNS        | **Hetzner (any)**   | VPS-only resilience; CP or worker OK, DB is replicated |
| kube-api-proxy  | VPS (DaemonSet)     | Kubeconfig access on public IPs                        |
| Gateway/Ingress | **VPS only**        | VPS-only resilience + public IP                        |
| Website         | **VPS only**        | VPS-only resilience                                    |
| Nebula          | **VPS lighthouses** | VPS-only resilience                                    |

### Soft Constraints (Decided)

| Service   | Prefer  | Fallback | Reason                     |
| --------- | ------- | -------- | -------------------------- |
| Inventree | Proxmox | n/a      | Nice-to-have, not critical |
| Grocy     | Proxmox | n/a      | Nice-to-have, not critical |
| Matrix    | Proxmox | n/a      | Not critical               |
| Gitea     | Proxmox | n/a      |                            |
| nix-cache | Proxmox | n/a      |                            |
| Atuin     | Proxmox | n/a      |                            |
| Props     | Proxmox | n/a      |                            |

## Per-Service Placement

Legend: **bold** = decision made, normal = current state / TBD.

### Core Infrastructure (stateless / minimal storage)

| Service                | Placement           | Storage | Notes                                          |
| ---------------------- | ------------------- | ------- | ---------------------------------------------- |
| sealed-secrets         | TBD                 | none    |                                                |
| tofu-controller        | TBD                 | none    | Scope reduced 47→7 resources (see <sso.md>)    |
| reloader               | TBD                 | none    |                                                |
| cert-manager           | TBD                 | none    |                                                |
| external-dns           | TBD                 | none    |                                                |
| metrics-server         | TBD                 | none    |                                                |
| vpa                    | TBD                 | none    |                                                |
| goldilocks             | TBD                 | none    |                                                |
| descheduler            | TBD                 | none    |                                                |
| node-feature-discovery | TBD                 | none    |                                                |
| nvidia-device-plugin   | **wyrm2**           | none    | GPU only on wyrm2                              |
| reflector              | TBD                 | none    |                                                |
| cnpg operator          | TBD                 | none    |                                                |
| coredns-custom         | TBD                 | none    |                                                |
| hubble-ui              | TBD                 | none    |                                                |
| dns-automation         | TBD                 | none    |                                                |
| longhorn               | TBD                 | n/a     | TBD: keep longhorn at all?                     |
| Kyverno                | **Any (incl. CPs)** | none    | Admission controller, colocate with API server |

### Auth & Security

| Service          | Placement   | Storage              | CSI        | Replication    | Notes                   |
| ---------------- | ----------- | -------------------- | ---------- | -------------- | ----------------------- |
| Authentik        | VPS         | CNPG VPS-HA (2 inst) | local-path | CNPG streaming | Migrating to Authelia   |
| Vault            | VPS-capable | Raft on local-path   | local-path | Raft internal  | Dropping (see <sso.md>) |
| external-secrets | TBD         |                      |            |                | Goes away with Vault    |

### DNS & Networking

| Service        | Placement         | Storage              | CSI        | Notes                             |
| -------------- | ----------------- | -------------------- | ---------- | --------------------------------- |
| **PowerDNS**   | **Hetzner (any)** | CNPG VPS-HA (2 inst) | local-path | CP or worker OK, DB is replicated |
| **Gateway**    | **VPS**           | none                 |            | Cilium Envoy hostNetwork          |
| kube-api-proxy | **VPS DaemonSet** | none                 |            |                                   |

### Data Services

| Service           | Current | Proposed    | Storage                          | CSI                | Replication | Notes        |
| ----------------- | ------- | ----------- | -------------------------------- | ------------------ | ----------- | ------------ |
| Gitea             | Proxmox | **Proxmox** | CNPG (1 inst) + proxmox-csi PVC  | proxmox-csi-retain | None        |              |
| Harbor            | Proxmox | TBD         | CNPG (1 inst) + proxmox-csi PVCs | proxmox-csi-retain | None        |              |
| Matrix            | Proxmox | **Proxmox** | CNPG (1 inst)                    | local-path         | None        | Not critical |
| nix-cache (Attic) | Proxmox | **Proxmox** | CNPG (1 inst) + proxmox-csi PVC  | proxmox-csi-retain | None        |              |
| Atuin             | Proxmox | **Proxmox** | CNPG (1 inst)                    | local-path         | None        |              |
| tofu-state DB     | VPS     | TBD         | CNPG VPS-HA (2 inst)             | local-path         | CNPG        |              |
| Props             | Proxmox | **Proxmox** | CNPG (1 inst)                    | local-path         | None        |              |

### Monitoring & Observability

| Service         | Current      | Proposed                    | Storage    | Replication         | Notes                             |
| --------------- | ------------ | --------------------------- | ---------- | ------------------- | --------------------------------- |
| Prometheus      | wyrm2 (6 Gi) | **Replace with VM cluster** | —          | —                   | See VictoriaMetrics section below |
| VictoriaMetrics | —            | **VPS workers**             | local-path | Built-in (factor=2) | 2x vmstorage on VPS workers       |
| Grafana         | ?            | VPS workers                 | local-path | None                | Stateless-ish, rebuildable        |
| Loki            | Proxmox      | TBD                         | MinIO?     | Via MinIO           | See <storage.md>                  |
| Alloy           | ?            | Any                         |            |                     | DaemonSet, stateless              |
| Tempo           | ?            | VPS workers                 | local-path | None                | Rebuildable                       |
| AlertManager    | ?            | VPS workers                 | local-path | None                |                                   |
| Gatus           | ?            | VPS workers                 | local-path | None                |                                   |

#### VictoriaMetrics Cluster (replaces Prometheus)

Replace Prometheus with VictoriaMetrics cluster mode. ~3-10x less RAM
for the same data. Built-in replication, PromQL-compatible, Grafana
works as-is (Prometheus datasource type).

**Components:**

- `vmstorage` (x2): One per VPS worker, local-path storage,
  `replicationFactor=2` — each metric written to both nodes
- `vminsert` (x1): Receives remote-write from scrapers, distributes
  to storage nodes. Lightweight, can run anywhere.
- `vmselect` (x1): Serves PromQL queries, merges/deduplicates from
  both storage nodes. Lightweight, can run anywhere.

**Cross-site replication problem:** `vminsert` writes to
`replicationFactor` nodes synchronously with no topology awareness.
If vmstorage nodes span VPS + Proxmox, some writes cross the 20ms
Nebula link. Plan for **vmstorage on VPS only** with 2 nodes.

**Migration path:**

1. Deploy VM cluster alongside Prometheus
2. Configure dual remote-write (Alloy writes to both)
3. Verify dashboards work against vmselect
4. Switch Grafana datasource to vmselect
5. Remove Prometheus

### Agent / AI Services

| Service              | Current           | Proposed          | Storage | Notes                         |
| -------------------- | ----------------- | ----------------- | ------- | ----------------------------- |
| **Ollama**           | Proxmox           | **Proxmox/wyrm2** |         | **Hard: GPU**                 |
| **LiteLLM**          | ?                 | **Proxmox**       |         | Colocate with Ollama          |
| OpenClaw             | Proxmox (gateway) | **Proxmox**       |         |                               |
| Airlock              | VPS               | **VPS (later)**   |         | Consider moving to VPS worker |
| google-workspace-mcp | ?                 | TBD               |         |                               |
| tana-mcp             | Proxmox           | TBD               |         |                               |
| homeassistant-proxy  | ?                 | TBD               |         |                               |

### Misc

| Service             | Current  | Proposed            | Storage          | Notes                             |
| ------------------- | -------- | ------------------- | ---------------- | --------------------------------- |
| Headlamp            | ?        | TBD                 | none             |                                   |
| Scanner             | Proxmox  | TBD                 |                  | NFS for printer scans, behind SSO |
| ActivityWatch       | Proxmox  | TBD                 | proxmox-csi (1G) |                                   |
| Grocy               | ?        | **Proxmox (wyrm2)** | local-path       | Nice-to-have, not critical        |
| Website             | VPS      | **VPS only**        | none (stateless) | VPS-only resilience               |
| Proxmox-proxy       | Proxmox  | **Proxmox**         | none             | Hard: needs VLAN to 10.2.0.2      |
| BuildBuddy executor | scaled 0 | TBD                 |                  |                                   |

### Suspended Services

| Service   | Reason                     | Decision                                            |
| --------- | -------------------------- | --------------------------------------------------- |
| Inventree | VPS OOM (2026-03-17)       | **Proxmox (wyrm2)** when unsuspended. Nice-to-have. |
| Kagent    | ?                          | Keep suspended                                      |
| Langfuse  | Degraded Longhorn on wyrm2 | Keep suspended                                      |
| Firecrawl | ?                          | Keep suspended                                      |

## Decided

- **Vault**: Drop (replaced by SOPS + age). See <sso.md>.
- **SSO**: Authentik → Authelia. See <sso.md>.
- **Prometheus**: Replace with VictoriaMetrics cluster.
- **Longhorn**: Drop after migrating remaining PVCs. See <storage.md>.

## Remaining Decisions

### Tier 1: Blocking

1. **Prometheus + Loki long-term placement.** See <storage.md>.

### Tier 2: Should decide

2. **Monitoring stack placement** (Grafana, Alloy, Tempo, AlertManager,
   Gatus).
3. **Harbor placement.** Effectively Proxmox-pinned via proxmox-csi.
4. **tofu-state DB.** Currently VPS-HA CNPG. Stays on VPS workers?
5. **Light services on CPs.** Candidates: PowerDNS, kube-api-proxy,
   Gateway/Ingress, Kyverno, CoreDNS, system DaemonSets.
6. **Hcloud CSI.** Remove or use for VPS worker storage?

### Tier 3: Low risk

7. **Stateless core infra** — run anywhere, prefer workers.
8. **Agent services** — Proxmox-preferred.
9. **Misc** (Headlamp, Scanner, ActivityWatch, BuildBuddy executor).
10. **Suspended services** — keep suspended for now.
11. **CNPG backup strategy.** Standardize pg_dump CronJobs.

## Migration

### Completed

- Longhorn restricted to Hetzner only (removed `proxmox-longhorn` SC, Kyverno
  proxmox rule, NixOS PATH policy; manager/driver pinned to
  `topology.kubernetes.io/region: hetzner`)
- 2x CPX31 VPS workers provisioned (Nebula lighthouses + relays,
  IPs 10.42.0.11/10.42.0.12)
- Descheduler deployed
- VPS CPs rebuilt as pure control planes (no workloads)
- `local-path-hetzner` and `local-path-proxmox` StorageClasses created
- Longhorn default SC annotation disabled (`persistence.defaultClass: false`)
- CLEANUP comments on all `local-path` and `longhorn` storage references
- Missing `storageClassName` fixed (airlock, gitea)
- SOPS age keypair infrastructure in tofu (`persistent-auth.tf`)
- `.sops.yaml` creation rule for `cluster/k8s/` paths
- Authelia manifests scaffolded (`k8s/authelia/`): Deployment, Service,
  HTTPRoute (`authelia.allegedly.works`), ConfigMap with OIDC provider
  config and local user backend. TODO markers for SOPS secrets, JWKS
  key, user password hash, and OIDC client definitions.

### Phase 1: Foundation (remaining)

1. Run `tofu apply` to generate age keypair, then manually copy the public key
   from `cluster/sops-cluster-secrets-public-key.txt` into the `&cluster-secrets`
   anchor in `.sops.yaml`. (Tofu writes the public key file; `.sops.yaml` is a
   hand-edited config that references it. No automation connects them — same
   pattern as sealed-secrets-cert.pem, which is tofu-managed but manually
   referenced by `seal-secret.sh`.)
2. Generate Authelia SOPS secrets (`authelia-secrets`, `authelia-jwks`),
   user password hash, uncomment SOPS resources in kustomization + Flux
3. Update `cnpg-conventions.md` for region-explicit storage classes
4. Migrate CNPG clusters + PVCs from generic `local-path` to `local-path-{region}`
5. Migrate monitoring/vault off bare `longhorn` SC

### Phase 2: CP Isolation (remaining)

6. Deploy PriorityClasses (`system-critical`, `important`, `batch`)
7. Pin Proxmox workloads with hard `nodeSelector`
8. Pin VPS-critical workloads
9. Move SSO + Flux controllers to VPS workers
10. Verify VPS CPs are near-pure

### Phase 3: SSO Migration (Authentik → Authelia)

See <sso.md> for detailed migration strategy.

11. Add first OIDC client to Authelia config (Headlamp — low risk)
12. Migrate apps one by one (OIDC → proxy-mode → service accounts)
13. Suspend Authentik, Vault, ESO
14. After validation: delete Authentik, Vault, ESO code

### Phase 4: Monitoring Migration (Prometheus → VictoriaMetrics)

16. Deploy VictoriaMetrics cluster
17. Configure dual remote-write
18. Verify + switch Grafana datasource
19. Remove Prometheus

### Phase 5: Storage (evaluate and migrate)

See <storage.md> for validation plans.

20. Evaluate MinIO site replication + HAProxy
21. Evaluate Loki/Tempo on MinIO
22. Evaluate JuiceFS OR Rook/Ceph
23. Migrate remaining Longhorn PVCs
24. Decommission Longhorn

### Phase 6: Cleanup

25. Remove Longhorn operator and CRDs
26. Remove Vault, ESO, tofu-controller secret resources
27. Remove Authentik namespace
28. Update cluster docs
