# Cluster Roadmap

**Last Updated**: 2026-02-13

## 🔥 Immediate Next Steps

**Status**: Cluster torn down. Pending bootstrap with GPU worker node.

### Next: Bootstrap with GPU Worker

GPU worker infrastructure is committed. Before bootstrapping:

1. **Restart wyrm** (manual) — releases GPUs detached in previous session
2. **Bootstrap**: `bazel run //cluster:bootstrap`
3. **Verify GPU worker**:
   ```bash
   kubectl get nodes -l nvidia.com/gpu=true
   kubectl get pods -n nvidia-device-plugin
   kubectl describe node talos-pve-gpu-worker-0 | grep nvidia.com/gpu
   # Expect: nvidia.com/gpu: 2
   ```

### Previous Bootstrap Verification (2026-02-12) ✅

All checks passed (pre-GPU worker, 3 nodes):

- **KubeSpan**: All peers "up", unique identities, no duplicates (2 peers per node × 3 nodes)
- **Nodes**: All 3 Ready (talos-vps-cp-0, talos-vps-cp-1, talos-pve-cp-0)
- **Kustomizations**: 62/62 non-suspended Ready at revision `f219691f`
- **Certificates**: All 16 Ready, no pending ACME challenges
- **Cross-node networking**: VPS↔Proxmox working (KubeSpan mesh healthy)

### Recent Fixes (2026-02-12/13)

1. **Element-web crashloop** — `enableServiceLinks: false` prevents Kubernetes from injecting
   `ELEMENT_WEB_PORT=tcp://...` which collides with the nginx template variable `${ELEMENT_WEB_PORT}`.
2. **Harbor proxy cache quay adapter** — Harbor v2.14 doesn't support `quay` as a proxy cache
   adapter type. Changed to `docker-registry` (Quay.io implements standard Docker V2 API).
3. **Gitea SSO `x509: certificate signed by unknown authority`** — CA trust bundle was only
   mounted in init containers (`extraInitVolumeMounts`) but not the main Gitea container.
   Added `extraContainerVolumeMounts` so `SSL_CERT_FILE` points to a path that actually exists.
4. **Website unsuspended** — removed `suspend: true` from flux-kustomization manifest.
5. **Proxmox VM balloon minimum** — increased from 4GB to 12GB (`floating = 12 * 1024`).

### Previous Fixes (2026-02-11)

1. **Cilium stripped to Talos-recommended defaults** + `MTU: 1370` + hubble.
   Reverted DNS workarounds to defaults. Note: the Helm key is uppercase `MTU`
   (case-sensitive; lowercase `mtu` is silently ignored).
2. **Machine secrets moved from layer 00 to layer 01** — fresh `cluster.id` per
   lifecycle prevents stale KubeSpan discovery entries from previous incarnations.
3. **HostnameConfig conflict fixed** — removed explicit HostnameConfig from VPS
   config patches (hcloud platform auto-sets hostname from server name).
4. **Install retries on all HelmReleases** — `install.remediation.retries: 3` on
   all 27 HelmReleases to prevent transient failures from permanently blocking bootstrap.
5. **Kyverno HA** — admission controller runs 3 replicas spread across control plane
   nodes with topology constraints, eliminating cross-node webhook calls during bootstrap.
6. **ClusterIP readiness gate** — bootstrap script verifies ClusterIP routing from
   every node before deploying Flux (closes the Cilium health-vs-BPF-maps gap).
7. **Vault `disable_mlock: true`** — required since Vault 1.20 (no longer defaults).
   Safe on Talos (no swap).
8. **`authentik-secrets` missing dependency on `authentik-token`** — `authentik-bootstrap`
   ExternalSecret reads `kv/sso/client-secrets` from Vault, but that path is created
   by `authentik-token` Terraform. Without the dependency, both kustomizations start in
   parallel after `external-secrets-config` is Ready, and the ExternalSecret fails
   with "Secret does not exist" because the Terraform hasn't populated Vault yet.

### Suspended Kustomizations

These kustomizations have `suspend: true` and need unsuspending when ready to deploy:

- **Kagent**: `kagent`, `kagent-namespace`, `kagent-secrets`, `authentik-blueprint-kagent`

### Next Actions

- [ ] **Switch cert-manager to production Let's Encrypt** — staging certs break SSO for
      all services (Gitea, Grafana, Harbor, Matrix) because OIDC discovery hits the ingress
      which serves untrusted staging certs. Single-line switch in
      `k8s/cert-manager-environment/flux-kustomization.yaml` (change `overlays/staging` → `overlays/production`).
      Well within rate limits (14 certs vs 50/week limit per registered domain).
- [ ] **Test all SSO flows** after switching to production LE
- [ ] **Deploy headscale**, test with a device
- [ ] **Deploy Ollama** — manifests committed, pending bootstrap verification (GPU node + auth proxy).
- [ ] **Ollama: investigate Authentik user tokens for per-user auth** — currently uses a single
      shared API key from Vault. Authentik supports per-user app passwords that can be exchanged
      for JWTs via `client_credentials` grant. Could replace the static shared key with per-user
      tokens (similar to how Harbor generates per-user CLI secrets after OIDC login). Requires
      Authentik proxy provider + long-lived JWTs for OpenAI SDK compatibility (SDK sends static
      Bearer token, no refresh). See Harbor's pattern: OIDC login → user generates CLI secret.
- [ ] **Deploy Node Feature Discovery (NFD)** — auto-detects GPU hardware via PCI scanning,
      sets `feature.node.kubernetes.io/pci-10de.present=true`. Eliminates manual `nvidia.com/gpu`
      label in Talos machine config and `affinity: {}` override in NVIDIA device plugin chart.
      Minimal overhead (~50m CPU, ~300Mi across 4 nodes). Helm chart: `node-feature-discovery`
      from `https://kubernetes-sigs.github.io/node-feature-discovery/charts`.
- [ ] **Migrate headscale to Helm chart** — currently raw deployment manifests, should use official
      Helm chart for consistency with other applications.
- [ ] Rename `monitoring-stack` → `kube-prometheus` or `prometheus-grafana`

### Known Issues to Watch

- **BuildBuddy executor** — 3 replicas running, connected to `remote.buildbuddy.io`. Container
  image warmup timed out (non-critical, images pulled on first build).
- **Kyverno webhook timeouts** — verified fixed (see previous fixes)

---

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
| Website        | Static placeholder | -   |

## Applications (disabled - need flux-kustomization.yaml)

| App       | Purpose          | Status                                       |
| --------- | ---------------- | -------------------------------------------- |
| Firecrawl | Web scraping API | Helm chart + manifests exist, needs enabling |
| Devbot    | Agent workload   | Manifests exist, needs enabling              |

TODO: Re-add flux-kustomization.yaml files and integrate into root kustomization.yaml
when ready to deploy these applications.

---

## 🚨 Minimal Requirements for Go-Live

### Public Traffic Routing

| Status | ✅ Configured (hostNetwork) |
| ------ | --------------------------- |

ingress-nginx and PowerDNS run with `hostNetwork: true`, binding directly to VPS node IPs.

**Traffic flow**:

```text
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

### VPS IP Configuration

✅ **Automated via DNS Automation** (tofu-controller)

After cluster boots:

- Route 53 glue records (ns1/ns2.allegedly.works) are created automatically
- PowerDNS NS A records within zone are created automatically
- VPS IPs are read from `cluster-info` ConfigMap created by infrastructure terraform

All VPS IP configuration is fully automated via `cluster-info` ConfigMap + Reflector.

### Registrar DNS Configuration

✅ **Route 53 glue records managed by tofu-controller**

NS delegation is configured at Route 53 (zone `Z02901943N8ZFQFOD9P5I`):

- NS records pointing to ns1/ns2.allegedly.works
- Glue A records automatically updated when VPS IPs change

### PowerDNS Zone

Create zone for `allegedly.works` in PowerDNS (update `k8s/powerdns-zones/clusterzone.yaml`).

### Deferred

`k8s/applications/atlas-proxy/` - not needed for go-live, atlas access via headscale mesh instead.

---

## 📋 Migration Path

### Phase 1: Cluster Bootstrap

1. [ ] Run `bazel run //cluster:bootstrap` to create VPS nodes (new public IPs assigned)
2. [ ] Verify VPS IPs in ConfigMap:
   ```bash
   kubectl get configmap cluster-info -n kube-system -o jsonpath='{.data.vps_nodes}' | jq
   ```
3. [x] ~~Update cluster configs with new VPS IPs~~ - **Automated via DNS automation**
   - Route 53 glue records: tofu-controller creates automatically
   - PowerDNS NS A records: tofu-controller creates automatically
   - external-dns `--default-targets`: automated via `cluster-info` ConfigMap + Reflector
4. [ ] Verify DNS automation applied:
   ```bash
   kubectl get terraform dns-records -n flux-system
   aws route53 list-resource-record-sets --hosted-zone-id Z02901943N8ZFQFOD9P5I \
     --query "ResourceRecordSets[?Name=='ns1.allegedly.works.']"
   ```
5. [ ] Verify DNS resolution: `dig @ns1.allegedly.works allegedly.works`
6. [ ] Verify certs issue: `kubectl get certificates -A`

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

## 🔧 Operational Hardening

### ESO Password Generator Volatility Fix

**Problem**: ESO Password generators regenerate on every `refreshInterval`. Applications that persist
credentials (PostgreSQL, Authentik) don't auto-update, causing authentication failures after refresh.

**Resolved**: All Password generators replaced with Vault SSOT. ExternalSecrets now read
stable values from Vault (24h refresh is safe since values don't change).

#### Phase 1: Reloader Adoption ✅ Complete

Stakater Reloader auto-restarts pods when secrets change. All services have
`reloader.stakater.com/auto: "true"` annotation.

#### Phase 2: Vault SSOT Migration ✅ Complete

All ESO Password generators replaced with Vault KV sources. Terraform generates once → stores in Vault →
ESO reads stable value.

**All secrets migrated to Vault SSOT** (per-service Terraform modules with isolated state):

| Secret                       | Terraform module                        | Vault path               | Status  |
| ---------------------------- | --------------------------------------- | ------------------------ | ------- |
| PowerDNS API key             | `terraform/gitops/powerdns-api-key/`    | `kv/powerdns/api-key`    | ✅ Done |
| Authentik API token          | `terraform/gitops/authentik-token/`     | `kv/sso/client-secrets`  | ✅ Done |
| Harbor admin password        | `terraform/gitops/harbor-admin/`        | `kv/harbor/admin`        | ✅ Done |
| Authentik PostgreSQL pw      | `terraform/gitops/authentik-passwords/` | `kv/authentik/passwords` | ✅ Done |
| Authentik admin pw           | `terraform/gitops/authentik-passwords/` | `kv/authentik/passwords` | ✅ Done |
| Authentik secret key         | `terraform/gitops/authentik-passwords/` | `kv/authentik/passwords` | ✅ Done |
| Gitea admin pw               | `terraform/gitops/gitea-admin/`         | `kv/gitea/admin`         | ✅ Done |
| Matrix signing/reg/macaroon  | `terraform/gitops/matrix-secrets/`      | `kv/matrix/secrets`      | ✅ Done |
| Grafana admin pw             | `terraform/gitops/grafana-admin/`       | `kv/grafana/admin`       | ✅ Done |
| User password (agentydragon) | `terraform/gitops/user-passwords/`      | `kv/users/agentydragon`  | ✅ Done |

Zero ESO Password generators remain. All ExternalSecrets now read stable values from Vault.

Also fixed: external-dns Reloader annotation, cert-manager ClusterIssuer `apiKeySecretRef` namespace.

See <lessons_learned/2025-11-28-eso-password-generator-desync.md> for detailed analysis.

---

### Kyverno GitOps Enforcement

**Status**: ✅ Deployed (Audit mode)

Kyverno deployed with `require-gitops` ClusterPolicy. Separated into own kustomization with
ValidatingWebhookConfiguration health check to ensure webhook is operational before other
workloads deploy.

**Location**: `k8s/kyverno/` (separate from core)

**Dependency chain**: cert-manager → kyverno → sealed-secrets/tofu-controller/metrics-server → everything else

**Current mode**: `validationFailureAction: Audit` - logs violations but doesn't block.
Change to `Enforce` after validation in live cluster.

---

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

---

### TODO: Remote Proxmox API Access

**Current state**: Proxmox API only reachable via VLAN IP (10.2.0.2) from home network.

- CSI driver uses 10.2.0.2:8006 (works because pods run on Proxmox VMs)
- Terraform provisioning also uses 10.2.0.2:8006 (only works from home)

**Future enhancement**: Split CSI and provisioning hosts, or add Tailscale route.

Options:

1. **Separate variables** - `proxmox_csi_host` (10.2.0.2) vs `proxmox_api_host` (Tailscale)
2. **Tailscale on Proxmox VLAN** - Route 10.2.0.0/16 via Tailscale for remote access
3. **Keep as-is** - Accept that Proxmox provisioning requires home network

---

### TODO: Multi-Endpoint Kubeconfig via DNS

**Current state**: `local_file.kubeconfig` points to a single VPS IP (the bootstrap node). If that node is down, `kubectl` can't connect.

**Desired state**: Kubeconfig uses a DNS name (e.g., `api.allegedly.works`) that resolves to all control plane nodes. Clients automatically fail over to a healthy node.

**Prerequisites**: Cluster DNS (PowerDNS) must be running first — chicken-and-egg with bootstrap.

**Implementation**:

1. Add `api.allegedly.works` A records pointing to all VPS control plane IPs (via DNS automation)
2. Change `local_file.kubeconfig` to use `https://api.allegedly.works:6443`
3. Bootstrap still needs direct IP for initial kubeconfig (before DNS is available)
4. Post-bootstrap step: regenerate kubeconfig with DNS name once DNS is live

---

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

---

### TODO: GitHub Webhook for Instant Reconciliation

**Problem**: Flux polls git repository on interval (default 1m). Changes aren't applied instantly.

**Solution**: Configure GitHub webhook to notify Flux receiver, triggering immediate reconciliation on push.

**Implementation**:

1. Create Flux `Receiver` resource (webhook endpoint)
2. Create sealed secret with webhook token
3. Configure GitHub repo webhook to POST to receiver URL
4. Receiver triggers GitRepository reconciliation

**Reference**: <https://fluxcd.io/flux/guides/webhook-receivers/>

---

### Flux Reconciliation Failure Alerts

**Status**: ✅ Configured

- ntfy.sh push notifications: `k8s/flux-system/flux-alerts.yaml`
- Grafana/Prometheus alerting: `k8s/monitoring-stack/flux-prometheus-rule.yaml`

---

### TODO: Flux Kustomization Dependency Graph UI

**Priority**: Low

Deploy a web UI that visualizes Flux kustomization status and dependency DAG as a node/edge graph.

**Options**:

- **Weave GitOps** — official Flux UI, shows kustomizations, HelmReleases, sources, dependency graph. Helm chart at `oci://ghcr.io/weaveworks/charts/weave-gitops`.
- **Capacitor** — lighter Flux dashboard, less mature.
- **Custom Grafana panel** — Flux Prometheus metrics exist but no dependency graph support.

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

### GPU Worker Node

2x RTX 5090 moved from wyrm VM to a dedicated Talos GPU worker node.

**Completed**:

- [x] Wyrm VM reconfigured (GPUs detached, RAM reduced to 8GB-64GB balloon)
- [x] GPU Talos image schematic with NVIDIA extensions (`nvidia-open-gpu-kernel-modules`, `nvidia-container-toolkit`)
- [x] PCI hardware mappings (`gpu0`, `gpu1`) via Proxmox API token (requires `Mapping.Modify,Mapping.Use`)
- [x] GPU worker VM: 8 cores, 32GB fixed RAM (balloon incompatible with VFIO), 2x RTX 5090 PCIe passthrough
- [x] NVIDIA machine config: kernel modules, `bpf_jit_harden`, containerd nvidia runtime, `nvidia.com/gpu` label
- [x] NVIDIA device plugin DaemonSet (`k8s/nvidia-device-plugin/`)

**Remaining (Ollama + Auth)**:

- [ ] Create Ollama Deployment with GPU resource request + PVC for models
- [ ] Add OpenAI-compatible API auth (Bearer token validated by nginx ingress `auth-snippet`,
      token stored in Vault). This allows using the OpenAI SDK with
      `base_url="https://ollama.allegedly.works/v1"` and a static API key.
- [ ] Expose via `ollama.allegedly.works` with TLS
- [ ] Newer Ollama supports the OpenAI responses API — verify compatibility

**TODO**: Revisit virtio-mem for dynamic memory on GPU VMs (and wyrm) when Proxmox adds support (Bugzilla #2949).
Currently balloon is incompatible with VFIO — QEMU actively inhibits it (`virtio-balloon.c:69-77`).

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

## 🔗 Related Documentation

- **Bootstrap Procedures**: <bootstrap.md>
- **Troubleshooting**: <troubleshooting.md>
- **Secret Sync Analysis**: <lessons_learned/2025-11-28-eso-password-generator-desync.md>

---

## 📊 Cluster Specifications

- **Nodes**: 3 (2 VPS control-plane, 1 Proxmox control-plane)
- **Talos**: v1.12.3
- **Kubernetes**: v1.35.1
- **CNI**: Cilium (VXLAN tunnel mode)
- **Monthly Cost**: ~€30 (2x CPX31 + backups)
