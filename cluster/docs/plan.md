# Cluster Roadmap

**Last Updated**: 2026-01-03

## 🎯 Current Status

**Major Architecture Change** (2026-01-03):

Migrated from Proxmox-only 5-node cluster to **hybrid Hetzner VPS + Proxmox** architecture:

- ✅ 2x Hetzner CPX31 VPS nodes deployed (Hillsboro, OR)
- ✅ Both nodes are control-plane with Talos v1.9.5, Kubernetes v1.32.0
- ✅ Cilium CNI with VXLAN tunnel mode (cross-node connectivity verified)
- ✅ Talos machine secrets persisted in 00-persistent-auth layer
- ✅ KubePrism (localhost:7445) for cluster_endpoint (breaks circular dependency)
- ✅ **KubeSpan mesh working** - WireGuard handshakes verified, state: `up` on both peers
- ✅ **Simplified VPS deployment using Hetzner public Talos ISO** (no custom snapshot needed)
- ✅ **Hetzner Cloud CSI** for block storage
- ⏳ Home Proxmox node(s) not yet added

**Current Cluster State**:

- Nodes: `talos-vps-0` (5.78.106.249), `talos-vps-1` (5.78.43.147)
- All core pods running: CoreDNS, Cilium, Hubble, hcloud-csi
- Node labels: `topology.kubernetes.io/region=hetzner`, `zone=hil`
- KubeSpan: Active mesh with ~15s handshake intervals
- No services deployed yet (Flux, Vault, etc. pending)

---

## 🔀 Possible Directions

From current state, several independent branches can be pursued:

### Branch A: Add Home Proxmox Node(s)

Extend cluster with home infrastructure for storage-heavy workloads.

**Prerequisites**:

1. Add Proxmox API credentials to 00-persistent-auth
2. Upload Talos ISO to Proxmox storage
3. Create `proxmox-nodes.tf` (similar to `hetzner-nodes.tf`)

**Steps**:

- [ ] Add Proxmox provider credentials to terraform state
- [ ] Create Talos VM template on Proxmox
- [ ] Deploy 1+ Proxmox nodes as workers
- [ ] Verify KubeSpan mesh connectivity (VPS ↔ home)
- [ ] Deploy Proxmox CSI for home storage

**Benefits**: ZFS storage access, media serving, heavy workloads at home

### Branch B: Terraform State Backup (rclone + Google Drive)

Protect terraform state with encrypted cloud backup.

**Implementation**:

- [ ] Configure rclone with Google Drive
- [ ] Encrypt terraform state before upload
- [ ] Create backup script in scripts/
- [ ] Document restore procedure
- [ ] Optional: Automated backup on terraform apply

**Scope**: `terraform/*/terraform.tfstate` files (contain all secrets)

### Branch C: Deploy Core Services (VPS-only)

Run services on VPS nodes without home Proxmox.

**Limitations**: No persistent storage (Proxmox CSI unavailable), ephemeral only

**Possible services**:

- [ ] Flux CD (GitOps)
- [ ] Sealed Secrets controller
- [ ] Ingress (nginx or Cilium Gateway API)
- [ ] cert-manager (DNS-01 via external provider)
- [ ] External services using Hetzner Block Storage

**Use case**: Lightweight public-facing services, CI/CD

### Branch D: Hetzner Block Storage CSI

Enable persistent storage on VPS nodes without Proxmox.

**Implementation**:

- [ ] Deploy hcloud-csi-driver
- [ ] Create StorageClass for Hetzner volumes
- [ ] Test PVC provisioning

**Benefits**: Enables stateful workloads on VPS-only cluster
**Limitations**: 10GB minimum, €0.052/GB/month, no RWX

### Branch E: Full Hybrid Bootstrap

Complete the original hybrid vision with all services.

**Combines**: Branch A + existing service stack

**Phases**:

1. Add Proxmox node(s) (Branch A)
2. Deploy Proxmox CSI for home storage
3. Deploy Vault with Raft HA
4. Deploy full service stack (Authentik, Harbor, Gitea, etc.)
5. Bootstrap script verification

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

### Kubeconfig HA via DNS Round-Robin

**Decision**: Use DNS name instead of single VPS IP for kubeconfig

**Target**:

```yaml
server: https://api.test-cluster.agentydragon.com:6443
```

**Implementation**:

- `api.test-cluster.agentydragon.com` → both VPS IPs (5.78.43.147, 5.78.106.249)
- DNS round-robin provides client-side failover
- Created by external-dns from Ingress annotation or manual DNS record

**Bootstrap**: Initial kubeconfig uses raw IP, switched to DNS after cluster is up and DNS records exist

### PowerDNS HA with Galera (VPS-local storage)

**Decision**: Run HA PowerDNS on both VPS nodes with MariaDB Galera using local storage

**Architecture**:

```
VPS0                         VPS1
├── local-path PVC           ├── local-path PVC
│   └── MariaDB data         │   └── MariaDB data
├── MariaDB (Galera) ◄─sync─►├── MariaDB (Galera)
└── PowerDNS pod             └── PowerDNS pod
```

**Benefits**:

- ❌ No AXFR complexity (same database = same data)
- ❌ No VPS standalone PowerDNS container needed
- ✅ True active-active DNS
- ✅ Survives single VPS failure
- ✅ No Hetzner Volume cost (uses VPS NVMe)

**DNS records**:

- `ns1.agentydragon.com` → VPS0 IP
- `ns2.agentydragon.com` → VPS1 IP

**Node placement**:

- `local-path-provisioner` on VPS nodes
- MariaDB Galera StatefulSet with `podAntiAffinity` (one pod per VPS)
- PowerDNS DaemonSet or Deployment with VPS node affinity

**Tradeoff**: If VPS is destroyed, that node's data is lost. But Galera syncs continuously, so the other node has the data. Only loses data if both VPS die simultaneously.

### VPS Controllers on Headscale

**Decision**: Add VPS controllers to Headscale mesh for additional connectivity options

**Benefits**:

- Backup path to API if public IP is blocked
- Tailscale MagicDNS as alternative to public DNS
- Unified management with other Headscale nodes

### Machine Secrets in Persistent Auth

**Decision**: Store Talos machine secrets in 00-persistent-auth layer

**Rationale**:

- Secrets persist across cluster destroy/recreate
- All nodes share same cluster identity
- Enables hybrid addition of nodes without regenerating secrets

### Storage Strategy: Consolidated VPS, Liberal Home

**Decision**: Minimize Hetzner volumes, consolidate databases; generous allocations on Proxmox

**Hetzner Block Storage** (~$0.54/10GB minimum per volume):

- **Shared PostgreSQL** - Single instance for Vault, Authentik, etc.
- **Vault Raft** - If not using shared PG (small, 10GB)
- Target: 2-3 volumes max on VPS (~$1.60/month)

**Proxmox CSI** (ZFS, no per-volume cost):

- Harbor registry + PostgreSQL (100GB+)
- Gitea + PostgreSQL (50GB+)
- Loki log storage (100GB+)
- Media services (Jellyfin, \*arr stack)
- Nix cache (100GB+)
- Be generous with allocations - storage is "free" from ZFS pool

**Service Placement**:

| Location | Services                                       | Rationale                            |
| -------- | ---------------------------------------------- | ------------------------------------ |
| VPS      | Vault, Authentik, Ingress, DNS, cert-manager   | Always-on, critical path             |
| Home     | Harbor, Gitea, Loki, Grafana, media, Nix cache | Storage-heavy, can tolerate downtime |

**Shared PostgreSQL Pattern**:

- Single PostgreSQL pod on VPS with Hetzner volume
- Multiple databases: `vault`, `authentik`, etc.
- Reduces PVC count from N to 1
- CloudNativePG or Bitnami PostgreSQL chart

---

## ✅ Recent Accomplishments

### 2026-01-02: Hetzner ISO Boot Simplification

- Switched from custom Talos snapshots to **Hetzner public Talos ISO** (ID: 122630)
- Removed obsolete components:
  - `terraform/hetzner-image/` layer (no longer needed)
  - `scripts/create-hetzner-talos-image.sh`
  - `hcloud-upload-image` tool from shell.nix
- ISO boots → reads user_data → auto-installs to disk → reboots
- Eliminates snapshot creation step, simplifies deployment

### 2026-01-03: Hybrid Infrastructure Foundation

- Migrated from Proxmox-only to hybrid Hetzner+Proxmox architecture
- Deployed 2x CPX31 VPS nodes with Talos
- Implemented Cilium VXLAN tunnel mode for cloud networking
- Added machine secrets to persistent auth layer
- Fixed regenerate-attic-jwt.sh to use terraform state (not libsecret)
- Added VXLAN firewall rule (UDP 8472)

### Previous Milestones (Proxmox-only era)

- 5-node Talos cluster (3 controllers, 2 workers)
- Full service stack: Vault, Authentik, Harbor, Gitea, Matrix
- Observability: Prometheus, Loki, Grafana with SSO
- DNS: PowerDNS with AXFR to VPS
- Certificates: cert-manager with DNS-01

---

## 🔗 Related Documentation

- **VPS Integration Design**: `docs/vps-cluster-integration.md`
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
