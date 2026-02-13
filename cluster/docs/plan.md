# Cluster Roadmap

**Last Updated**: 2026-02-13

## 🔥 Immediate Next Steps

**Status**: Cluster running with 4 nodes (2 VPS + 1 Proxmox CP + 1 GPU worker).
Authentik auth fixes committed, pending reconciliation.

### Recent Fixes (2026-02-13)

1. **Authentik MFA blocking login** — Default authentication flow has an MFA validation stage
   that rejects users with no enrolled authenticator devices ("Empty response"). Created custom
   flow without MFA stage via Terraform (`sso/users/main.tf`), set as default via `authentik_brand`.
2. **Authentik admin password env var wrong** — `authentik-admin-password` ExternalSecret created
   key `password`, but Authentik expects `AUTHENTIK_BOOTSTRAP_PASSWORD`. Fixed to use direct
   `secretKey` matching the env var name (consistent with other 3 Authentik ESOs).
3. **Authentik bootstrap token ESO inconsistency** — Removed unnecessary template from
   `bootstrap-external-secret.yaml`, now uses direct `secretKey: AUTHENTIK_BOOTSTRAP_TOKEN`
   (consistent with `secret-key` and `postgres` ESOs).
4. **Proxmox CSI controller on wrong node** — Chart uses top-level `nodeSelector`, not
   `controller.nodeSelector`. Misplaced key was silently ignored, CSI controller landed on VPS
   where Proxmox API (10.2.0.2:8006) is unreachable. Cascaded to all Proxmox-storage workloads.
5. **Missing `admin-user`/`username` keys in ESO secrets** — Grafana and Gitea charts expect
   both username and password keys. ESO templates only had password from Vault. Added static
   username fields to ESO `target.template.data`.
6. **Gitea admin-token Job reads username from secret** — Job now sources `GITEA_ADMIN_USERNAME`
   from the `gitea-admin-password` secret instead of hardcoding `admin`.

### Suspended Kustomizations

- **Kagent**: `kagent`, `kagent-namespace`, `kagent-secrets`, `authentik-blueprint-kagent`

### Next Actions

- [ ] **Switch cert-manager to production Let's Encrypt** — staging certs work for SSO
      (LE staging root CA is in the trust bundle via `cluster-ca` staging overlay), but
      browsers show certificate warnings. Single-line switch in
      `k8s/cert-manager-environment/flux-kustomization.yaml` (change `overlays/staging` → `overlays/production`).
      Well within rate limits (14 certs vs 50/week limit per registered domain).
- [ ] **Test all SSO flows** — run `scripts/check-authentik-login.py` and test browser login
- [ ] **Re-enable MFA** (TOTP/WebAuthn) once device enrollment is set up. Current custom flow
      in `terraform/gitops/sso/users/main.tf` skips MFA. Add enrollment stage + MFA validation
      stage back when ready.
- [ ] **Wire `scripts/check-authentik-login.py` into bootstrap/CI** — currently manual.
      Consider adding to `bootstrap.py` health checks or as a flux kustomization health check.
- [ ] **Deploy headscale**, test with a device
- [x] **Verify Ollama** — 2x RTX 5090 detected (CUDA 12.0, 31.8 GiB each), auth proxy working
      (401 on unauthenticated, 200 with Bearer token), ingress at `ollama.allegedly.works`,
      OpenAI-compatible `/v1/chat/completions` tested with `smollm2:135m`, all 31/31 layers on GPU.
- [ ] **Ollama: per-user auth** — investigate Authentik user tokens (app passwords →
      `client_credentials` JWTs). Currently uses shared API key from Vault.
- [ ] **Consider removing `gitea-admin-token` Job** — originally created for Terraform to
      configure Gitea OAuth via admin API, but SSO moved to the Authentik blueprint pattern.
      Nothing currently consumes the token secret. May still be useful for future Gitea API
      automation (repo/org management).
- [ ] Rename `monitoring-stack` → `kube-prometheus` or `prometheus-grafana`
- [ ] **Verify ntfy.sh notifications** — confirm Flux reconciliation failure alerts
      actually arrive on phone via ntfy.sh push notifications.

## 🎯 Target Architecture

The cluster will run entirely on Talos:

- **2x Hetzner VPS** - Control plane nodes with public IPs
- **1+ Proxmox VMs** - Control plane + workers on home server (atlas)

No separate ansible-managed VPS. Everything currently on the VPS must move into the cluster.

**End state**: Cluster handles everything on `allegedly.works` (test) then `agentydragon.com` (production).

## Domain Strategy

| Domain             | Purpose                     | Status                  |
| ------------------ | --------------------------- | ----------------------- |
| `allegedly.works`  | Test/staging cluster        | Active, serving traffic |
| `agentydragon.com` | Production (future cutover) | On ansible VPS          |

## Current Nodes

| Node                   | Location | Role          | IP            |
| ---------------------- | -------- | ------------- | ------------- |
| talos-vps-cp-0         | Hetzner  | control-plane | (new on boot) |
| talos-vps-cp-1         | Hetzner  | control-plane | (new on boot) |
| talos-pve-cp-0         | Proxmox  | control-plane | 10.2.1.1      |
| talos-pve-gpu-worker-0 | Proxmox  | worker (GPU)  | 10.2.2.1      |

## Core Services (already configured)

| Component              | Status | Notes                                      |
| ---------------------- | ------ | ------------------------------------------ |
| Flux CD                | ✅     | GitOps                                     |
| ingress-nginx          | ✅     | hostNetwork on VPS nodes                   |
| cert-manager           | ✅     | DNS-01 via PowerDNS                        |
| PowerDNS               | ✅     | hostNetwork on VPS nodes                   |
| Vault                  | ✅     | With OIDC auth                             |
| Authentik              | ✅     | SSO provider                               |
| External Secrets       | ✅     | Vault integration                          |
| Monitoring             | ✅     | Prometheus/Grafana/Loki                    |
| Proxmox CSI            | ✅     | Storage for home nodes                     |
| local-path-provisioner | ✅     | Storage for VPS nodes                      |
| Stakater Reloader      | ✅     | Deployed, adopted (7/7 services)           |
| DNS Automation         | ✅     | tofu-controller manages Route53 + PowerDNS |
| Node Feature Discovery | ✅     | Auto-detects GPU/hardware, provides labels |
| NVIDIA Device Plugin   | ✅     | GPU resource registration on GPU nodes     |

## Applications (already configured)

| App            | Purpose            | SSO |
| -------------- | ------------------ | --- |
| Harbor         | Container registry | ✅  |
| Gitea          | Git hosting        | ✅  |
| Matrix/Element | Chat               | ✅  |
| Nix cache      | Binary cache       | -   |
| BuildBuddy     | Remote build exec  | -   |
| Headscale      | Tailscale control  | -   |
| Ollama         | LLM inference      | -   |
| Website        | Static placeholder | -   |

## Applications (disabled - need flux-kustomization.yaml)

| App       | Purpose          | Status                                       |
| --------- | ---------------- | -------------------------------------------- |
| Firecrawl | Web scraping API | Helm chart + manifests exist, needs enabling |
| Devbot    | Agent workload   | Manifests exist, needs enabling              |

TODO: Re-add flux-kustomization.yaml files and integrate into root kustomization.yaml
when ready to deploy these applications.

---

## 🚨 Go-Live Checklist

Completed infrastructure: public traffic routing (hostNetwork ingress+DNS), kubectl access,
DNS automation (Route 53 + PowerDNS via tofu-controller), cert-manager, VPS IP automation.

### Remaining

- [ ] Deploy headscale, test with a device, join atlas to mesh
- [ ] Website accessible on test domain, then `agentydragon.com`
- [ ] Test all services on `allegedly.works`
- [ ] Migrate Tailscale devices from ansible VPS to cluster headscale
- [ ] Update `agentydragon.com` DNS to point to cluster
- [ ] Decommission ansible-managed VPS

## 🔧 Operational Hardening

### Secrets: Vault SSOT ✅ Complete

All application secrets use Terraform → Vault → ESO pattern. Zero ESO Password generators
remain. Stakater Reloader restarts pods on secret changes. See
<lessons_learned/2025-11-28-eso-password-generator-desync.md> for historical context.

### Kyverno GitOps Enforcement ✅

Deployed in Audit mode. `require-gitops` ClusterPolicy, HA (3 replicas).
TODO: Switch to `Enforce` after validation.

### TODO: Firewall Hardening

**Problem**: All cluster ports exposed to 0.0.0.0/0 including K8s API, Talos API, etcd, kubelet.

**Current state** (`terraform/bootstrap/infrastructure/main.tf` lines 128-221):

```hcl
# All rules have: source_ips = ["0.0.0.0/0", "::/0"]
```

**Recommended changes**:

| Port        | Service      | Current   | Should Be                 |
| ----------- | ------------ | --------- | ------------------------- |
| 80, 443     | HTTP/HTTPS   | 0.0.0.0/0 | ✅ Keep (public ingress)  |
| 53          | DNS          | 0.0.0.0/0 | ✅ Keep (public DNS)      |
| 6443        | K8s API      | 0.0.0.0/0 | Restrict to known IPs     |
| 50000-50001 | Talos API    | 0.0.0.0/0 | Restrict to known IPs     |
| 51820       | KubeSpan     | 0.0.0.0/0 | Restrict to VPS + Proxmox |
| 8472        | Cilium VXLAN | 0.0.0.0/0 | Restrict to VPS + Proxmox |
| 2379-2380   | etcd         | 0.0.0.0/0 | Restrict to VPS + Proxmox |
| 10250       | kubelet      | 0.0.0.0/0 | Restrict to VPS + Proxmox |

**Implementation approach**:

```hcl
locals {
  # Known admin IPs (update with your IPs)
  admin_ips = ["YOUR_HOME_IP/32", "YOUR_MOBILE_IP/32"]

  # Inter-node communication (VPS public IPs + Proxmox subnet via KubeSpan)
  cluster_ips = concat(
    [for s in hcloud_server.vps : "${s.ipv4_address}/32"],
    ["10.2.0.0/16"]  # Proxmox subnet reachable via KubeSpan
  )
}

# K8s API - admin only
rule {
  port       = "6443"
  source_ips = local.admin_ips
}

# etcd - cluster internal only
rule {
  port       = "2379-2380"
  source_ips = local.cluster_ips
}
```

### TODO: Remote Proxmox API Access

**Current state**: Proxmox API only reachable via VLAN IP (10.2.0.2) from home network.

- CSI driver uses 10.2.0.2:8006 (works because pods run on Proxmox VMs)
- Terraform provisioning also uses 10.2.0.2:8006 (only works from home)

**Future enhancement**: Split CSI and provisioning hosts, or add Tailscale route.

Options:

1. **Separate variables** - `proxmox_csi_host` (10.2.0.2) vs `proxmox_api_host` (Tailscale)
2. **Tailscale on Proxmox VLAN** - Route 10.2.0.0/16 via Tailscale for remote access
3. **Keep as-is** - Accept that Proxmox provisioning requires home network

### TODO: Multi-Endpoint Kubeconfig via DNS

**Current state**: `local_file.kubeconfig` points to a single VPS IP (the bootstrap node). If that node is down, `kubectl` can't connect.

**Desired state**: Kubeconfig uses a DNS name (e.g., `api.allegedly.works`) that resolves to all control plane nodes. Clients automatically fail over to a healthy node.

**Prerequisites**: Cluster DNS (PowerDNS) must be running first — chicken-and-egg with bootstrap.

**Implementation**:

1. Add `api.allegedly.works` A records pointing to all VPS control plane IPs (via DNS automation)
2. Change `local_file.kubeconfig` to use `https://api.allegedly.works:6443`
3. Bootstrap still needs direct IP for initial kubeconfig (before DNS is available)
4. Post-bootstrap step: regenerate kubeconfig with DNS name once DNS is live

### TODO: Terraform State Backup

**Problem**: If `terraform/bootstrap/persistent-auth/terraform.tfstate` is lost, all SealedSecrets become
undecryptable. This is the single source of truth for the sealed-secrets keypair.

**Current state**: Local file only, no backup.

**Options**:

1. **rclone + Google Drive** (documented in Future Directions below)
2. **Encrypted S3/GCS backend** - Terraform native, but exposes to cloud provider
3. **git-crypt in separate repo** - Version controlled but complex
4. **Manual backup script** - Simple, run after `terraform apply`

**Minimum viable implementation**:

```bash
#!/bin/bash
# scripts/backup-terraform-state.sh
set -e
BACKUP_DIR="$HOME/gdrive-backup/terraform-state"
mkdir -p "$BACKUP_DIR"
for state in terraform/*/terraform.tfstate; do
  cp "$state" "$BACKUP_DIR/$(dirname $state | tr / -)-$(date +%Y%m%d).tfstate"
done
echo "Backed up to $BACKUP_DIR"
```

Add to post-apply hook or document as manual step.

### TODO: GitHub Webhook for Instant Reconciliation

**Problem**: Flux polls git repository on interval (default 1m). Changes aren't applied instantly.

**Solution**: Configure GitHub webhook to notify Flux receiver, triggering immediate reconciliation on push.

**Implementation**:

1. Create Flux `Receiver` resource (webhook endpoint)
2. Create sealed secret with webhook token
3. Configure GitHub repo webhook to POST to receiver URL
4. Receiver triggers GitRepository reconciliation

**Reference**: <https://fluxcd.io/flux/guides/webhook-receivers/>

### TODO: Flux Kustomization Dependency Graph UI

**Priority**: Low

Deploy a web UI that visualizes Flux kustomization status and dependency DAG as a node/edge graph.

**Options**:

- **Weave GitOps** — official Flux UI, shows kustomizations, HelmReleases, sources, dependency graph. Helm chart at `oci://ghcr.io/weaveworks/charts/weave-gitops`.
- **Capacitor** — lighter Flux dashboard, less mature.
- **Custom Grafana panel** — Flux Prometheus metrics exist but no dependency graph support.

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

### GPU Worker Node ✅

2x RTX 5090 on dedicated Talos GPU worker node (`talos-pve-gpu-worker-0`). 8 cores, 32GB
fixed RAM (balloon incompatible with VFIO), NFD + NVIDIA device plugin, Ollama deployed
with openresty auth proxy at `ollama.allegedly.works`.

**TODO**: Revisit virtio-mem when Proxmox adds support (Bugzilla #2949).

### BuildBuddy Remote Executor ✅

Deployed and verified. 3 replicas connected to `remote.buildbuddy.io`, pinned to Proxmox nodes.
Container image warmup timed out on first boot (non-critical, images pulled on first build).

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

## 📋 Future Services (Lower Priority)

- [ ] Jellyfin (media streaming)
- [ ] \*arr stack (media automation)
- [ ] Paperless-ngx (document management)
- [ ] Syncthing (file sync)
- [ ] Bazel Remote Cache

## 🔧 Low Priority Improvements

### Nix Cache Signing Key → GitOps Terraform

**Status**: Considering

Currently the nix cache signing key lives in Layer 0 (persistent-auth terraform state).
Consider moving it to a gitops terraform module (like other secrets) so it's generated/stored
in Vault and read via ESO. This would:

- Remove one item from the "critical to back up" persistent-auth layer
- Follow the same Vault SSOT pattern as all other application secrets
- Allow rotation without touching persistent-auth

**Trade-off**: Signing key change invalidates all previously signed store paths in the cache.
This is acceptable if the cache is treated as ephemeral (can always rebuild from source).

### ReadWriteMany (RWX) Shared Storage

**Status**: Planning

Need shared storage mountable from multiple pods (and ideally via NFS from non-cluster VMs)
for workloads like LLM model snapshots, media libraries, shared caches.

**Best options for our hybrid VPS+Proxmox architecture:**

| Option                            | RWX | HA  | Complexity | Best for                       |
| --------------------------------- | --- | --- | ---------- | ------------------------------ |
| `nfs-subdir-external-provisioner` | Yes | No  | Low        | Simple shared storage from NFS |
| Rook-Ceph                         | Yes | Yes | High       | Distributed HA storage         |
| Longhorn                          | No  | Yes | Medium     | Block storage only (no RWX)    |
| MinIO                             | S3  | Yes | Medium     | Object storage (not POSIX)     |
| Native Proxmox NFS export         | Yes | No  | Minimal    | Quick and dirty                |

**Recommended approach**: NFS-based provisioner (low complexity, proven). Export NFS from Proxmox
host or a small NFS VM on atlas. Accessible from VPS pods via KubeSpan mesh.

**Availability zones** (storage placement strategy):

| Zone       | Storage backend   | Use case                         |
| ---------- | ----------------- | -------------------------------- |
| Home-only  | Proxmox NFS/CSI   | LLM snapshots, media, Nix cache  |
| VPS-only   | local-path/hcloud | Vault raft, small critical-path  |
| Cross-site | NFS via KubeSpan  | Shared config, small shared data |

**Note**: Cross-site NFS via KubeSpan adds latency. Large data (LLM models) should be
home-only; only small shared data should go cross-site.

- [ ] Export NFS from Proxmox (or create NFS VM on atlas)
- [ ] Deploy `nfs-subdir-external-provisioner` Helm chart
- [ ] Create `nfs-shared` StorageClass with RWX access mode
- [ ] Test cross-site NFS access from VPS pods via KubeSpan

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

**Decision**: VXLAN tunnel mode (not native routing), Talos-recommended defaults only

**Rationale**:

- Hetzner VPS nodes are not on same L2 network
- Native routing fails: "gateway must be directly reachable"
- VXLAN encapsulates pod traffic between nodes
- KubeSpan docs warn non-default Cilium options cause "asymmetric routing"
- `MTU: 1370` in Helm values (uppercase key — case-sensitive, lowercase is silently ignored)
- Avoids fragmentation: VXLAN overhead (50) + WireGuard overhead (80) = 130, so 1500 - 130 = 1370

**Firewall**: UDP 8472 required for VXLAN overlay

See <lessons_learned/2026-02-11-cilium-mtu-cross-node-packet-loss.md>
for network stack diagrams and diagnostic checklist.

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
┌────────────────────────────────────────────────────────────┐
│  ExternalDNS (watches Ingress → auto-creates A records)    │
│  powerdns-operator (ClusterZone CRD → manages zones)       │
└─────────────────────┬──────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────────────────┐
│  PowerDNS (Deployment, connects to Galera)                 │
└─────────────────────┬──────────────────────────────────────┘
                      ↓
┌────────────────────────────────────────────────────────────┐
│  MariaDB Galera (3-node, synchronous replication)          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │ VPS-0     │◄►│ VPS-1     │◄►│ Proxmox   │               │
│  │ local-path│  │ local-path│  │ local-path│               │
│  └───────────┘  └───────────┘  └───────────┘               │
└────────────────────────────────────────────────────────────┘
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

## 🔗 Related Documentation

- **Bootstrap Procedures**: <bootstrap.md>
- **Troubleshooting**: <troubleshooting.md>
- **Secret Sync Analysis**: <lessons_learned/2025-11-28-eso-password-generator-desync.md>

## 📊 Cluster Specifications

- **Nodes**: 4 (2 VPS control-plane, 1 Proxmox control-plane, 1 Proxmox GPU worker)
- **Talos**: v1.12.3
- **Kubernetes**: v1.35.1
- **CNI**: Cilium (VXLAN tunnel mode)
- **Monthly Cost**: ~€30 (2x CPX31 + backups)
