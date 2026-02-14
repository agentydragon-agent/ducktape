# Cluster Roadmap

**Last Updated**: 2026-02-13

## 🔥 Immediate Next Steps

**Status**: Cluster running with 4 nodes (2 VPS + 1 Proxmox CP + 1 GPU worker).
76/76 non-suspended kustomizations Ready. Authentik auth verified (both `agentydragon` and `akadmin`).
Gitea SSO tested and working.

### Recent Fixes (2026-02-13)

1. **Dual ClusterIssuer with single-toggle switching** — Two always-present ClusterIssuers
   (`letsencrypt-prod`, `letsencrypt-staging`). Active issuer selected by a single ConfigMap
   (`k8s/cert-manager-issuer-config/configmap.yaml`). Every Ingress has
   `cert-manager.io/cluster-issuer: "${LETSENCRYPT_ISSUER}"` annotation substituted by Flux,
   so flipping the toggle re-issues all certificates. Trust bundle also follows the toggle
   via `${LETSENCRYPT_ISSUER}-root-ca` naming convention (staging CA only trusted in staging
   mode). `ingressShim.defaultIssuerName` kept as fallback.
2. **Authentik MFA blocking login** — Custom flow without MFA stage via Terraform
   (`sso/users/main.tf`), domain-matched `authentik_brand`.
3. **Authentik ESO key naming** — All 4 Authentik ExternalSecrets now use direct `secretKey`
   matching the env var name (`AUTHENTIK_BOOTSTRAP_PASSWORD`, `AUTHENTIK_BOOTSTRAP_TOKEN`, etc.).
4. **Proxmox CSI `nodeSelector`** — chart uses top-level key, not `controller.nodeSelector`.
5. **ESO username keys** — Grafana/Gitea charts expect both username+password; added static
   username fields to ESO templates.

### Suspended Kustomizations

- **Kagent**: `kagent`, `kagent-namespace`, `kagent-secrets`, `authentik-blueprint-kagent`

### Next Actions

- [x] **Switch cert-manager to production Let's Encrypt** — done via dual-issuer toggle.
      Single ConfigMap in `k8s/cert-manager-issuer-config/` controls active issuer.
      Every Ingress has `cert-manager.io/cluster-issuer: "${LETSENCRYPT_ISSUER}"` annotation
      (Flux-substituted), so flipping the toggle re-issues all certs. Trust bundle follows
      via `${LETSENCRYPT_ISSUER}-root-ca` naming convention.
- [ ] **Test all SSO flows** — Gitea verified working. Run `scripts/check-authentik-login.py`.
      Remaining to test: Harbor, Grafana, Matrix, Vault OIDC login via browser.
- [ ] **Re-enable MFA** (TOTP/WebAuthn) once device enrollment is set up. Current custom flow
      in `terraform/gitops/sso/users/main.tf` skips MFA. Add enrollment stage + MFA validation
      stage back when ready.
- [ ] **Wire `scripts/check-authentik-login.py` into bootstrap/CI** — currently manual.
      Consider adding to `bootstrap.py` health checks or as a flux kustomization health check.
- [ ] **Deploy headscale**, test with a device
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

| Domain             | Purpose                      | Status                  |
| ------------------ | ---------------------------- | ----------------------- |
| `allegedly.works`  | Test cluster (prod LE certs) | Active, serving traffic |
| `agentydragon.com` | Production (future cutover)  | On ansible VPS          |

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
| cert-manager           | ✅     | DNS-01 via PowerDNS, dual-issuer toggle    |
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

## 📋 Production Cutover (`agentydragon.com`)

- [ ] Deploy headscale, migrate all devices from ansible VPS headscale
- [ ] Atlas Proxmox accessible via headscale mesh (or `atlas.allegedly.works` proxy)
- [ ] Website hosted in cluster, verify accessible
- [ ] Update `agentydragon.com` DNS to point to cluster
- [ ] Decommission ansible-managed VPS

### Headscale Bootstrap DNS Workaround

**Context**: Tailscale's bootstrap DNS (via DERP servers) only resolves `tailscale.com`
domains. With headscale using `agentydragon.com`, clients can't resolve the control
server on boot (chicken-and-egg: DNS is set to 100.100.100.100 which requires the
tunnel to be up first).

**Workaround**: Static `/etc/hosts` entry on atlas pointing `agentydragon.com`
to the VPS IP. Managed in `ansible/atlas.yaml` (atlas-specific, not in the role).

**When VPS changes**: Must re-run ansible on all tailscale clients to update the IP.
Eventually `agentydragon.com` will have multiple IPs (cluster VPS nodes) — the hosts
entry will need to list all of them or use a single stable entry point.

---

## 🔧 Operational Hardening

### Secrets: Vault SSOT ✅ Complete

All application secrets use Terraform → Vault → ESO pattern. Zero ESO Password generators
remain. Stakater Reloader restarts pods on secret changes. See
<lessons_learned/2025-11-28-eso-password-generator-desync.md> for historical context.

### Kyverno GitOps Enforcement ✅

Deployed in Audit mode. `require-gitops` ClusterPolicy, HA (3 replicas).
TODO: Switch to `Enforce` after validation.

### TODO: Firewall Hardening

All Hetzner firewall rules currently allow `0.0.0.0/0`. Keep 80/443/53 public; restrict
K8s API (6443), Talos API (50000-50001), etcd (2379-2380), kubelet (10250), KubeSpan (51820),
VXLAN (8472) to admin IPs and inter-node CIDRs.

### TODO: Remote Proxmox API Access

Proxmox API only reachable from home network (10.2.0.2:8006). CSI works (pods on Proxmox),
but `terraform apply` requires home network. Options: split CSI/provisioning hosts, add
Tailscale route, or accept limitation.

### TODO: Multi-Endpoint Kubeconfig via DNS

Kubeconfig points to single VPS IP. Use `api.allegedly.works` resolving to all CP nodes
for failover. Chicken-and-egg: bootstrap needs direct IP, post-bootstrap rewrites to DNS name.

### TODO: Terraform State Backup

`persistent-auth/terraform.tfstate` is the SSOT for sealed-secrets keypair — local file only,
no backup. Options: rclone+Google Drive, encrypted S3, git-crypt, or manual backup script.

### TODO: GitHub Webhook for Instant Reconciliation

Flux polls git on 1m interval. Add Flux `Receiver` + GitHub webhook for instant reconciliation
on push. See <https://fluxcd.io/flux/guides/webhook-receivers/>.

### TODO: Flux Kustomization Dependency Graph UI

Low priority. Weave GitOps or Capacitor for visualizing kustomization DAG.

## 🔀 Future Directions

### GPU Worker Node ✅

`talos-pve-gpu-worker-0`: 2x RTX 5090, 8 cores, 32GB fixed RAM, Ollama at `ollama.allegedly.works`.
TODO: Revisit virtio-mem when Proxmox adds support (Bugzilla #2949).

### BuildBuddy Remote Executor ✅

3 replicas on Proxmox, connected to `remote.buildbuddy.io`.

### Shared PostgreSQL / MariaDB Galera

Replace single-instance MariaDB (PowerDNS) with 3-node Galera cluster (VPS-0, VPS-1, Proxmox)
on `local-path` storage. 2/3 quorum survives single node failure. Could also serve as shared
PostgreSQL for multiple services.

## 📋 Future Services (Lower Priority)

- [ ] Jellyfin (media streaming)
- [ ] \*arr stack (media automation)
- [ ] Paperless-ngx (document management)
- [ ] Syncthing (file sync)
- [ ] Bazel Remote Cache

## 🔧 Low Priority Improvements

### Nix Cache Signing Key → GitOps Terraform

Consider moving signing key from persistent-auth to Vault SSOT (gitops terraform module).
Trade-off: invalidates existing cached store paths (acceptable if cache is ephemeral).

### ReadWriteMany (RWX) Shared Storage

Shared storage mountable from both cluster pods and non-cluster VMs (e.g., wyrm).
Use cases: LLM model snapshots, media libraries, shared caches. Cross-site access
via KubeSpan adds latency — large data should stay home-only.

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

PowerDNS runs in-cluster on VPS nodes with `hostNetwork: true` (no AXFR, single source of
truth). Future: MariaDB Galera (3-node) for DB redundancy. ExternalDNS + powerdns-operator
for declarative zone/record management.

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
