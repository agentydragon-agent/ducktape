# Cluster Roadmap

**Last Updated**: 2026-01-05

## 🎯 Current Status

**Hybrid Hetzner VPS + Proxmox** architecture operational:

- ✅ 2x Hetzner CPX31 VPS nodes (Hillsboro, OR) - control-plane
- ✅ 2x Proxmox nodes (atlas) - 1 control-plane + 1 worker
- ✅ Cilium CNI with VXLAN tunnel mode
- ✅ KubeSpan mesh (WireGuard) connecting VPS ↔ home
- ✅ Hetzner Cloud CSI + Proxmox CSI + local-path-provisioner
- ✅ Flux, Vault, Authentik, cert-manager deployed
- ⚠️ `talos-vps-cp-1` currently NotReady (needs investigation)

**Current Nodes**:

| Node               | Location | Role          | IP                      |
| ------------------ | -------- | ------------- | ----------------------- |
| talos-vps-cp-0     | Hetzner  | control-plane | 5.78.43.147             |
| talos-vps-cp-1     | Hetzner  | control-plane | 5.78.106.249 (NotReady) |
| talos-pve-cp-0     | Proxmox  | control-plane | 10.2.1.1                |
| talos-pve-worker-0 | Proxmox  | worker        | 10.2.2.1                |

**Pending**:

- [ ] Fix talos-vps-cp-1 NotReady state
- [ ] Complete DNS stack migration (see DNS Architecture below)

---

## 🔀 Possible Directions

### Branch A: Terraform State Backup (rclone + Google Drive)

Protect terraform state with encrypted cloud backup.

**Implementation**:

- [ ] Configure rclone with Google Drive
- [ ] Encrypt terraform state before upload
- [ ] Create backup script in scripts/
- [ ] Document restore procedure
- [ ] Optional: Automated backup on terraform apply

**Scope**: `terraform/*/terraform.tfstate` files (contain all secrets)

### Branch B: DNS Stack Migration

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

## 📋 Service Deployment (Once Storage Available)

### Core Infrastructure

- [ ] Flux CD with Sealed Secrets
- [ ] Vault with Raft HA (requires persistent storage)
- [ ] External Secrets Operator
- [ ] Authentik (identity provider)

### Platform Services

- [ ] Harbor (container registry, pull-through cache)
- [ ] Gitea (git hosting)
- [ ] Grafana + Prometheus + Loki (observability)
- [ ] Matrix/Synapse (chat)
- [ ] Nix Cache (Harmonia)

### Future Services (Lower Priority)

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

- Removed obsolete components:
  - `terraform/hetzner-image/` layer (no longer needed)
  - `scripts/create-hetzner-talos-image.sh`
  - `hcloud-upload-image` tool from shell.nix
- ISO boots → reads user_data → auto-installs to disk → reboots

### 2026-01-03: Hybrid Infrastructure Foundation

- Migrated from Proxmox-only to hybrid Hetzner+Proxmox architecture
- Deployed 2x CPX31 VPS nodes with Talos
- Implemented Cilium VXLAN tunnel mode for cloud networking
- Fixed regenerate-attic-jwt.sh to use terraform state (not libsecret)
- Added VXLAN firewall rule (UDP 8472)

### Previous Milestones (Proxmox-only era)

- 5-node Talos cluster (3 controllers, 2 workers)
- Observability: Prometheus, Loki, Grafana with SSO
- DNS: PowerDNS with AXFR to VPS
- Certificates: cert-manager with DNS-01

---

## 🔗 Related Documentation

- **VPS Integration Design**: `docs/vps_cluster_integration.md`
- **Bootstrap Procedures**: `docs/bootstrap.md`
- **Troubleshooting**: `docs/troubleshooting.md`
- **Secret Sync Analysis**: `docs/archive/SECRET_SYNCHRONIZATION_ANALYSIS.md`

---

## 📊 Current Metrics

**VPS Cluster** (2026-01-03):

- Nodes: 2 (both Ready, control-plane)
- Talos: v1.9.5
- Kubernetes: v1.32.0
- CNI: Cilium 1.16.x (VXLAN)
- Location: Hillsboro, OR (hil)

**Monthly Cost** (VPS only):

- 2x CPX31: ~€30/month total
- Backups enabled: +20%
