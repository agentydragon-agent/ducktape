# Cluster Roadmap

**Last Updated**: 2026-02-06

## 🎯 Target Architecture

The cluster will run entirely on Talos:

- **2x Hetzner VPS** - Control plane nodes with public IPs
- **1+ Proxmox VMs** - Control plane + workers on home server (atlas)

No separate ansible-managed VPS. Everything currently on the VPS must move into the cluster.

**End state**: Cluster handles everything on `allegedly.works` (test) then `agentydragon.com` (production).

## Domain Strategy

| Domain              | Purpose                    | Status                    |
| ------------------- | -------------------------- | ------------------------- |
| `allegedly.works`   | Test/staging cluster       | Registered, pending setup |
| `agentydragon.com`  | Production (future cutover)| On ansible VPS            |

## Current Nodes

| Node               | Location | Role          | IP           |
| ------------------ | -------- | ------------- | ------------ |
| talos-vps-cp-0     | Hetzner  | control-plane | (new on boot)|
| talos-vps-cp-1     | Hetzner  | control-plane | (new on boot)|
| talos-pve-cp-0     | Proxmox  | control-plane | 10.2.1.1     |
| talos-pve-worker-0 | Proxmox  | worker        | 10.2.2.1     |

## Core Services (already configured)

| Component              | Status | Notes                              |
| ---------------------- | ------ | ---------------------------------- |
| Flux CD                | ✅     | GitOps                             |
| MetalLB                | ✅     | VIP 10.2.3.2 for ingress           |
| ingress-nginx          | ✅     | hostNetwork on VPS nodes           |
| cert-manager           | ✅     | DNS-01 via PowerDNS                |
| PowerDNS               | ✅     | hostNetwork on VPS nodes           |
| Vault                  | ✅     | With OIDC auth                     |
| Authentik              | ✅     | SSO provider                       |
| External Secrets       | ✅     | Vault integration                  |
| Monitoring             | ✅     | Prometheus/Grafana/Loki            |
| Proxmox CSI            | ✅     | Storage for home nodes             |
| local-path-provisioner | ✅     | Storage for VPS nodes              |

## Applications (already configured)

| App          | Purpose            | SSO |
| ------------ | ------------------ | --- |
| Harbor       | Container registry | ✅  |
| Gitea        | Git hosting        | ✅  |
| Matrix/Element| Chat              | ✅  |
| Nix cache    | Binary cache       | -   |
| BuildBuddy   | Remote build exec  | -   |
| Test app     | Connectivity test  | -   |

---

## 🚨 Minimal Requirements for Go-Live

### Public Traffic Routing

| Status | ✅ Configured (hostNetwork) |
| ------ | --------------------------- |

ingress-nginx and PowerDNS run with `hostNetwork: true`, binding directly to VPS node IPs.

**Traffic flow**:
```
Internet → VPS public IP:443 → ingress-nginx pod (hostNetwork) → backend services
Internet → VPS public IP:53  → PowerDNS pod (hostNetwork) → DNS responses
```

**Failover via DNS**: DNS returns two A records (both VPS IPs). Modern browsers handle failover automatically.

### Website Hosting

| Status | ✅ Manifests created |
| ------ | -------------------- |

- [ ] Personal website accessible (test domain first, then `agentydragon.com`)
- **Current state**: Hakyll-built site, rsync to ansible VPS, served by nginx
- **Initial implementation**: Simple nginx + static HTML placeholder
- **Location**: `k8s/applications/website/`

### Atlas Proxmox Access

| Status | ✅ Via Headscale mesh |
| ------ | --------------------- |

- [ ] Atlas joins headscale mesh
- Access via tailscale IP: `ssh root@100.64.x.x` or `https://100.64.x.x:8006`
- No public ingress needed - internal mesh access only

**Dependency**: Requires headscale running first. Once atlas joins the mesh, it's accessible from any device in the tailnet.

**Deferred**: Public DNS access (`atlas.allegedly.works`) is optional - would require proxy pod on Proxmox worker or tailscale on VPS nodes. Not needed for go-live.

### Headscale Server

| Status | ✅ Manifests created |
| ------ | -------------------- |

- [ ] Headscale server running as cluster workload
- [ ] Stable public endpoint for Tailscale clients
- [ ] Persistent storage for database (SQLite on PVC)
- **Location**: `k8s/applications/headscale/`

**Architecture**: Headscale exposed via public ingress on VPS nodes. Non-cluster devices (laptops, phones, atlas) connect via public DNS.

### kubectl Access

| Status | ✅ Configured |
| ------ | ------------- |

- [x] Working kubectl access to the cluster
- Via KUBECONFIG from terraform output
- direnv auto-exports when in cluster directory

---

## ⚠️ Remaining Work Before Bootstrap

### Domain Switchover

✅ **Complete** - All manifests updated from `test-cluster.agentydragon.com` to `allegedly.works`

### VPS IP Configuration

After cluster boots and new VPS IPs are assigned:

1. Update `k8s/powerdns-zones/nameserver-glue-records.yaml` with new IPs
2. Update `k8s/external-dns/deployment.yaml` `--default-targets` with new IPs

### Registrar DNS Configuration

At registrar (where `allegedly.works` is registered), set:

| Record Type | Name                    | Value                          |
| ----------- | ----------------------- | ------------------------------ |
| NS          | allegedly.works         | ns1.allegedly.works            |
| NS          | allegedly.works         | ns2.allegedly.works            |
| A (glue)    | ns1.allegedly.works     | `<VPS-0 IP after boot>`        |
| A (glue)    | ns2.allegedly.works     | `<VPS-1 IP after boot>`        |

### PowerDNS Zone

Create zone for `allegedly.works` in PowerDNS (update `k8s/powerdns-zones/clusterzone.yaml`).

### Deferred

`k8s/applications/atlas-proxy/` - not needed for go-live, atlas access via headscale mesh instead.

---

## 📋 Migration Path

### Phase 1: Cluster Bootstrap

1. [ ] Boot fresh cluster (new VPS IPs assigned)
2. [ ] Update configs with new VPS IPs
3. [ ] Configure registrar DNS for allegedly.works
4. [ ] Verify DNS resolution and ingress work

### Phase 2: Deploy Missing Services

5. [ ] Deploy headscale, test with a device
6. [ ] Deploy website, verify accessible
7. [ ] Configure atlas proxy (update IP)
8. [ ] Test all services on allegedly.works

### Phase 3: Production Cutover

9. [ ] Migrate Tailscale devices from ansible VPS headscale to cluster headscale
10. [ ] Update `agentydragon.com` DNS to point to cluster
11. [ ] Decommission ansible-managed VPS

---

## 🔀 Future Directions

### Terraform State Backup (rclone + Google Drive)

Protect terraform state with encrypted cloud backup.

**Implementation**:

- [ ] Configure rclone with Google Drive
- [ ] Encrypt terraform state before upload
- [ ] Create backup script in scripts/
- [ ] Document restore procedure
- [ ] Optional: Automated backup on terraform apply

**Scope**: `terraform/*/terraform.tfstate` files (contain all secrets)

### GPU Workloads (Ollama + Auth Proxy)

Move GPU from standalone VM (wyrm) to k8s cluster for LLM inference.

**Current State**: RTX 5090 passed through to wyrm VM, Ollama running as systemd service

**Target State**: GPU passed to k8s worker node, Ollama in pod with auth proxy

**Architecture**:

```text
┌─────────────────────────────────────────────────────────────┐
│  Internet → Ingress → Auth Proxy → Ollama Pod              │
│                         ↓                                    │
│                   API Key Validation                        │
│                   (nginx/Caddy sidecar)                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  GPU Worker Node (Proxmox VM with PCIe passthrough)         │
│  - NVIDIA driver + container toolkit                        │
│  - Node label: nvidia.com/gpu=true                          │
│  - Talos extension: nvidia-container-toolkit                │
└─────────────────────────────────────────────────────────────┘
```

**Implementation**:

- [ ] Configure Proxmox VM with GPU passthrough (PCIe device 01:00)
- [ ] Add Talos nvidia-container-toolkit extension to worker image
- [ ] Deploy NVIDIA device plugin DaemonSet
- [ ] Create Ollama Deployment with GPU resource request
- [ ] Add auth proxy sidecar (nginx with `auth_request` or Caddy with `basicauth`)
- [ ] Store API keys in Vault, sync via ESO
- [ ] Expose via Ingress with TLS

**Auth Proxy Options**:

1. **nginx sidecar** - `auth_request` directive validates Bearer token against configmap/secret
2. **Caddy sidecar** - `basicauth` or forward_auth to validate API key
3. **oauth2-proxy** - Full OIDC if multi-user access control needed

**Why k8s instead of standalone VM**:

- Unified management (GitOps, monitoring, secrets)
- Easier scaling (add more GPU nodes)
- Ingress/TLS handled by existing infrastructure
- API key rotation via Vault/ESO

### BuildBuddy Remote Executor

Remote build execution via BuildBuddy Cloud.

**Status**: Deployed (pending cluster bring-up for verification)

**Implementation**:

- [x] HelmRelease using official `buildbuddy-executor` chart from `https://helm.buildbuddy.io`
- [x] API key sealed as SealedSecret, injected via Flux `valuesFrom`
- [x] Pinned to Proxmox nodes (`topology.kubernetes.io/region: proxmox`)
- [x] 2 replicas, 2 CPU / 8Gi limits each
- [ ] Verify executor connects to BuildBuddy Cloud after cluster bootstrap

**Location**: `k8s/applications/buildbuddy-executor/`

### Shared PostgreSQL / MariaDB Galera

Migrate from current single-instance MariaDB to replicated Galera cluster.

**Current State**: PowerDNS with single MariaDB on Proxmox CSI

**Target State**: PowerDNS + MariaDB Galera (3-node) + powerdns-operator

**Galera Node Placement** (for quorum):

| Node     | Location       | Storage    | Purpose       |
| -------- | -------------- | ---------- | ------------- |
| galera-0 | talos-vps-cp-0 | local-path | Primary VPS   |
| galera-1 | talos-vps-cp-1 | local-path | Secondary VPS |
| galera-2 | talos-pve-\*   | local-path | Tie-breaker   |

Any single node failure maintains 2/3 quorum.

**Implementation**:

- [ ] Deploy `mariadb-galera` as separate HelmRelease (Bitnami chart)
- [ ] Configure pod anti-affinity to spread across VPS + Proxmox
- [ ] Use `local-path` storage (no Hetzner volume costs)
- [ ] Modify PowerDNS to connect to Galera cluster
- [ ] Deploy `powerdns-operator` for ClusterZone CRD
- [ ] Create `powerdns-zones` with declarative zone + records
- [ ] Verify ExternalDNS auto-creates records from Ingress annotations

See **DNS Architecture** section below for details.

---

## 📋 Future Services (Lower Priority)

- [ ] Jellyfin (media streaming)
- [ ] \*arr stack (media automation)
- [ ] Paperless-ngx (document management)
- [ ] Syncthing (file sync)
- [ ] Bazel Remote Cache

---

## 📐 Architecture Decisions

### Hybrid VPS + Proxmox

**Rationale**:

- VPS for public ingress, DNS, always-on services
- Home for storage-heavy workloads, media, compute
- KubeSpan mesh provides encrypted connectivity
- Reduces single point of failure

**Network Design**:

- VPS nodes: Public IPs, control-plane role
- Home nodes: Private IPs (via KubeSpan), worker role
- Cilium VXLAN for pod overlay (tunnel mode required for VPS)

### CNI: Cilium with VXLAN

**Decision**: VXLAN tunnel mode (not native routing)

**Rationale**:

- Hetzner VPS nodes are not on same L2 network
- Native routing fails: "gateway must be directly reachable"
- VXLAN encapsulates pod traffic between nodes

**Firewall**: UDP 8472 required for VXLAN overlay

### KubePrism for Cluster Endpoint

**Decision**: Use `localhost:7445` as cluster_endpoint

**Rationale**:

- No VIP possible across VPS and home networks
- KubePrism runs on every node, proxies to available API servers
- Kubeconfig patched post-bootstrap to use real VPS IP

### DNS Architecture

**Decision**: PowerDNS + MariaDB Galera + powerdns-operator + ExternalDNS

**Old Architecture** (Proxmox-only era):

- Cluster PowerDNS on MetalLB VIP (internal)
- VPS PowerDNS in Docker (external, public-facing)
- AXFR replication from cluster → VPS
- Complex, two separate systems

**New Architecture** (Hybrid VPS + Proxmox):

- VPS nodes ARE Kubernetes nodes with public IPs
- PowerDNS pod runs directly in cluster, accessible via VPS public IPs
- No AXFR needed - single source of truth
- MariaDB Galera for database redundancy (3-node across VPS + Proxmox)

```text
┌─────────────────────────────────────────────────────────────┐
│  ExternalDNS (watches Ingress → auto-creates A records)    │
│  powerdns-operator (ClusterZone CRD → manages zones)       │
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│  PowerDNS (Deployment, connects to Galera)                 │
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│  MariaDB Galera (3-node, synchronous replication)          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ VPS-0     │◄─►│ VPS-1     │◄─►│ Proxmox   │              │
│  │ local-path│  │ local-path│  │ local-path│               │
│  └───────────┘  └───────────┘  └───────────┘               │
└─────────────────────────────────────────────────────────────┘
```

**Benefits**:

- No Hetzner volume costs (local-path storage)
- Survives single node failure (2/3 quorum)
- Fully declarative (zones via CRD, records via Ingress annotations)
- No AXFR complexity

**Components**:

- `mariadb-galera` - Bitnami Helm chart
- `powerdns` - Custom chart, connects to Galera
- `powerdns-operator` - Provides ClusterZone/ClusterRRset CRDs
- `external-dns` - Already deployed, auto-creates records

### Storage Strategy: Consolidated VPS, Liberal Home

**Decision**: Minimize Hetzner volumes, consolidate databases; generous allocations on Proxmox

#### VPS Storage (small, fast-access)

- **Vault Raft** - If not using shared PG (small, 10GB)
- Target: 2-3 volumes max on VPS (~$1.60/month)

#### Home Storage (large, tolerates downtime)

- Gitea + PostgreSQL (50GB+)
- Loki log storage (100GB+)
- Media services (Jellyfin, \*arr stack)
- Nix cache (100GB+)

| Location | Services                                       | Rationale                            |
| -------- | ---------------------------------------------- | ------------------------------------ |
| VPS      | Vault, Authentik, Ingress, DNS, cert-manager   | Always-on, critical path             |
| Home     | Harbor, Gitea, Loki, Grafana, media, Nix cache | Storage-heavy, can tolerate downtime |

#### Shared PostgreSQL Option

- Single PostgreSQL pod on VPS with Hetzner volume
- Multiple databases: `vault`, `authentik`, etc.
- Secrets persist across cluster destroy/recreate

---

## ✅ Recent Accomplishments

### 2026-02-06: Go-Live Preparation

- Registered `allegedly.works` test domain
- Configured ingress-nginx for hostNetwork mode on VPS nodes
- Configured PowerDNS for hostNetwork mode on VPS nodes
- Updated external-dns with dual VPS IP targets
- Created manifests for headscale, website, atlas-proxy

### 2026-01-03: Hybrid Infrastructure Foundation

- Migrated from Proxmox-only to hybrid Hetzner+Proxmox architecture
- Deployed 2x CPX31 VPS nodes with Talos
- Implemented Cilium VXLAN tunnel mode for cloud networking
- Added VXLAN firewall rule (UDP 8472)

### Previous Milestones

- Observability: Prometheus, Loki, Grafana with SSO
- DNS: PowerDNS with AXFR to VPS
- Certificates: cert-manager with DNS-01

---

## 🔗 Related Documentation

- **Bootstrap Procedures**: `docs/bootstrap.md`
- **Troubleshooting**: `docs/troubleshooting.md`
- **Secret Sync Analysis**: `docs/archive/SECRET_SYNCHRONIZATION_ANALYSIS.md`

---

## 📊 Cluster Specifications

- **Nodes**: 4 (2 VPS control-plane, 1 Proxmox control-plane, 1 Proxmox worker)
- **Talos**: v1.9.5
- **Kubernetes**: v1.32.0
- **CNI**: Cilium (VXLAN tunnel mode)
- **Monthly Cost**: ~€30 (2x CPX31 + backups)
