# Cluster Roadmap

**Last Updated**: 2025-12-10

## 🎯 Current Status

**Recent Accomplishments** (2025-12-10):

- ✅ Fixed Gitea 10-hour crash loop (OAuth config dependency issue)
- ✅ Implemented Let's Encrypt environment switching (staging/production)
- ✅ Added RWO volume deployment strategy protections (Harbor, Grafana, Gitea)
- ✅ Fixed Harbor SSO Terraform (data source → resource reference bug)
- ✅ Documented RWO volume deadlock pattern (3rd occurrence prevention)
- ✅ Consolidated and reorganized documentation (lowercase, DRY)

**Current Focus**: Cluster health verification and SSO stabilization

### Next Steps

1. **Bootstrap Test** - Verify turnkey deployment works end-to-end
   - Run `terraform destroy && ./bootstrap.sh`
   - Verify all services come up healthy
   - Test Gitea SSO login flow

2. **SSO Integration Completion**
   - Harbor SSO already configured (pending test)
   - Gitea SSO already configured (pending test)
   - Vault OIDC configured (pending test)

3. **Validate SSO Login Flows** - Browser testing required
   - [ ] Test Harbor OIDC login via browser
   - [ ] Test Gitea OIDC login via browser
   - [ ] Test Vault OIDC login via browser
   - [ ] Verify auto-onboarding creates users correctly
   - [ ] Verify group-based authorization (admin groups)

### Needs Investigation (Lower Priority)

- None currently

---

## 📋 Next Up (Prioritized Backlog)

### High Priority - Post-SSO Platform Services

### High Priority - Observability

- [x] ~~metrics-server~~ (DONE - kubectl top working)
- [x] ~~Prometheus stack~~ (DONE - kube-prometheus-stack deployed)
- [x] ~~Loki + Promtail~~ (DONE - log aggregation operational)
- [x] ~~Grafana SSO via Authentik OIDC~~ (DONE - OAuth login working)
- [ ] OpenTelemetry (distributed tracing - later when complexity warrants)

### Medium Priority - Platform Services

- [ ] **Jellyfin** - Media streaming server (Netflix alternative)
  - Hardware transcoding support
  - Mobile apps, web interface
  - Authentik SSO integration
- [ ] **Media Automation Stack** - Automated media management
  - **Radarr** (movies), **Sonarr** (TV shows)
  - **Prowlarr** (indexer management)
  - **Bazarr** (subtitles)
  - **Overseerr** (request management UI)
- [ ] **qBittorrent** - Torrent client with web UI
  - VPN integration via Gluetun sidecar
  - Automatic integration with *arr stack
- [ ] **agentydragon.com** - Migrate personal website to cluster
  - Static site or SSG deployment
  - HTTPS via cert-manager
  - DNS via external-dns
- [ ] **InvenTree** - Inventory management (TrueCharts v9.0.12)
- [ ] **Syncthing** - File synchronization (TrueCharts chart available)
- [ ] **Bazel Remote Cache** - Distributed build cache (slamdev/bazel-remote)

### Low Priority - Infrastructure & Operations

- [ ] **Secret Rotation Infrastructure** - Stakater Reloader for automatic pod restarts on secret changes
  - Phase 0 (stabilization) complete with 8760h refresh intervals
  - Phase 1 (Reloader deployment) complete - deployed to kube-system, watches all namespaces
  - Future phases: Fix init-time patterns, migrate to Vault KV, enable rotation
  - Reference: `docs/archive/SECRET_SYNCHRONIZATION_ANALYSIS.md`
- [x] ~~Complete SNI migration (move remaining VPS services to stream-level SNI)~~ (DONE - 2025-11-18)
- [ ] VPS proxy resilience testing (MetalLB VIP pod failure handling)
- [ ] Proxmox CSI orphaned volume cleanup (post-destroy automation)
- [ ] **Persistent Cache PVCs** - Preserve cache data across cluster destroy/recreate cycles
  - Target: Harbor pull-through cache, Bazel remote cache, similar services
  - Current: PVCs deleted on cluster destroy, lose all cached images/artifacts
  - Goal: Move cache PVCs to persistent layer (like 00-persistent-auth)
  - Benefit: Faster bootstrap iterations, reduced upstream registry bandwidth
  - Implementation: Separate Terraform layer or external PVC provisioning
- [ ] **Gitea Terraform Provider** - Automate repository and mirror management
  - Provider: `go-gitea/gitea` (registry.terraform.io/providers/go-gitea/gitea/latest)
  - Resources: `gitea_repository`, `gitea_org`, `gitea_oauth2_app`
  - Use cases: Provision mirrors, manage repos, configure OAuth apps
  - Note: Does NOT support authentication sources (use kubectl exec Job for OAuth login config)

---

## 🔬 Research & Evaluation

### Under Consideration

- [ ] **DNS Propagation Alternatives** - Faster updates than current AXFR
  - **Option 1: external-dns → VPS PowerDNS API** - Direct API updates via Tailscale
  - **Option 2: external-dns → Route53** - Bypass VPS, push directly to AWS
  - **Current issue**: AXFR NOTIFY from cluster has unpredictable source IP (pod can run on any node)
  - **Current workaround**: AXFR refresh every 3 hours (SOA refresh interval)
  - **Simple fix**: Reduce SOA refresh to 5-10 minutes

- [ ] **Technitium DNS** - Alternative to PowerDNS (modern, DNSSEC, web UI)
  - Pros: Better architecture, comprehensive features
  - Cons: RFC2136-only integration, newer to K8s ecosystem
  - Decision: Evaluate if features justify integration complexity

- [ ] **Guacamole + Authentik RAC** - Clientless remote desktop with SSO
  - Target: Browser-based VNC/RDP to Proxmox VMs (wyrm)
  - Value: Zero-click SSO graphical access
  - Status: Architecture defined, ready for deployment

- [ ] **Paperless-ngx** - Document management system
  - OCR, tagging, full-text search
  - Scan → automatic organization
  - Good for going paperless
  - Authentik SSO integration

- [ ] **Persistent AI Agents Platform** - Long-running agents with compute resources
  - Architecture: Kagent + MCP servers + per-agent containers
  - Phases: CLI prototype → visual capabilities → multi-agent → production hardening
  - Detail: See `docs/agents.md`

### Future Enhancements (Freezer)

- [ ] Universal HTTPS Auto-Transformer (Kustomization transformer for 1-line HTTPS)
- [ ] Advanced multi-tool resource ownership conflict detector
- [ ] Backup/recovery documentation and etcd backup automation
- [ ] Conditional Tailscale auth key provisioning (avoid regeneration)
- [ ] TFLint rule reconsideration (selectively re-enable disabled rules)
- [ ] Talos extensions: ZFS, NFS Utils, gVisor
- [ ] ActivityWatch server (requires custom Helm chart)
- [ ] Google Drive sync/backup (custom deployment with existing binary)

---

## ✅ Achieved Milestones

### Core Infrastructure (COMPLETE)

- **5-node Talos Cluster** (3 controllers, 2 workers, VIP HA)
- **CNI: Cilium** via Terraform (prevents circular dependency)
- **GitOps: Flux CD** with proper dependency ordering
- **Secrets Management**: Hybrid architecture
  - SealedSecrets for bootstrap (stable keypair in libsecret)
  - External Secrets Operator for runtime secrets from Vault
- **Turnkey Deployment**: `./bootstrap.sh` → working cluster
  - Layered terraform: 00-persistent-auth → 01-infrastructure → 02-services → 03-configuration

### Storage (COMPLETE)

- **Proxmox CSI** with native ZFS integration
  - SSH-based ephemeral token generation
  - Declarative cleanup with destroy provisioners
  - Talos topology labels and container runtime support
- **Vault with Raft** (3-node HA)
  - Bank-Vaults operator for auto-unsealing
  - Pod-specific addressing (instance-0/1/2)
  - Proxmox CSI persistent storage (10Gi per pod)

### Networking (COMPLETE)

- **MetalLB** L2 advertisement (ingress: 10.2.3.2, dns: 10.2.3.3, services: 10.2.3.4-20)
- **NGINX Ingress** with MetalLB LoadBalancer
- **VPS Proxy** via Tailscale with SNI passthrough on port 443

### DNS & Certificates (COMPLETE)

- **PowerDNS** authoritative server (10.2.3.3)
  - MariaDB backend with Proxmox CSI storage
  - ESO integration for API key management
  - AXFR zone replication to VPS (working with TCP MTU probing)
  - TCP MTU probing enabled for Tailscale PMTUD blackhole mitigation
- **external-dns** automatic ingress DNS record creation
- **cert-manager** with PowerDNS webhook for DNS-01 challenges
- **Tailscale route advertisement** (VPS→Cluster 10.2.3.0/27)
- **Let's Encrypt certificates** via DNS-01 solver (wildcard support)
- **Automatic DNS propagation** working end-to-end (3-hour refresh cycle)

### Platform Services (OPERATIONAL)

- **Vault** - Secret management with Raft HA
- **External Secrets Operator** - Vault→K8s secrets bridge
- **Authentik** - Identity provider with OIDC/SSO
- **Gitea** - Git service at git.test-cluster.agentydragon.com (SSO configured)
- **Harbor** - Container registry at registry.test-cluster.agentydragon.com (SSO configured)
  - **Pull-through cache**: Docker Hub, GHCR, Quay, registry.k8s.io proxy projects
  - **Talos registry mirrors**: Automatic fallback to upstream registries
- **Matrix/Synapse** - Chat platform with Authentik SSO at matrix.test-cluster.agentydragon.com
- **Firecrawl** - AI web scraping service (all components healthy)
- **metrics-server** - Kubernetes Metrics API (kubectl top working)
- **Prometheus Stack** - Complete metrics collection (6-node monitoring)
- **Loki + Promtail** - Log aggregation (19 namespaces, 7-day retention)
- **Stakater Reloader** - Automatic pod restarts on secret/configmap changes
- **Nix Cache** - Binary cache at cache.test-cluster.agentydragon.com (Harmonia)
  - Serves pre-built Nix derivations to NixOS hosts
  - Public read, authenticated uploads via Nix signing keys
  - 100Gi Proxmox CSI storage for /nix/store
  - Automatic HTTPS via cert-manager, DNS via external-dns

---

## 📐 Architecture Decisions

### CNI Management: Infrastructure vs. GitOps

**Decision**: Terraform manages Cilium (not Flux)

**Rationale**:

- Prevents circular dependency (GitOps tools managing their own networking)
- AWS EKS Blueprints, GKE Autopilot use same pattern
- Worker nodes require CNI before they can pull container images
- Flux updating CNI creates deadlock during network transitions

**Layer Separation**: Talos→CoreDNS, Terraform→CNI, Flux→Applications

### Secrets Management: Hybrid Approach

**Decision**: SealedSecrets for bootstrap, ESO for runtime

**Bootstrap Secrets** (SealedSecrets):

- Proxmox CSI credentials
- Flux deploy key
- Stable keypair in libsecret (survives cluster destroy)

**Runtime Secrets** (External Secrets Operator):

- Application passwords from Vault
- API keys and tokens
- No circular dependencies (Vault Stage 1 enables ESO)

### DNS Architecture: AXFR Secondary Zone

**Decision**: VPS PowerDNS as secondary (not forwarder)

**Architecture**:

- Primary: Cluster PowerDNS (10.2.3.3) - authoritative source
- Secondary: VPS PowerDNS - public-facing with AXFR replication
- Connectivity: Tailscale VPN with route advertisement
- **TCP MTU probing**: Enabled to handle Tailscale MTU (1280) vs pod MTU (1500) mismatch

**Requirements**:

- Cluster controlplane nodes advertise `10.2.3.0/27` subnet route via Tailscale
- VPS Tailscale must be configured with `--accept-routes` to receive advertised routes
- Talos kubelet configured to allow `net.ipv4.tcp_mtu_probing` unsafe sysctl
- PowerDNS pod runs in privileged namespace with TCP MTU probing enabled

**Rationale**: VPS runs PowerDNS authoritative (not recursor), requires AXFR. TCP MTU probing mitigates PMTUD
blackholes caused by Tailscale's lower MTU (RFC 4821).

**Known Limitation - NOTIFY:**

NOTIFY is **not configured** because it doesn't work in Kubernetes environments:

- **Why NOTIFY fails**: PowerDNS pod can run on any cluster node, resulting in unpredictable source IPs
  (100.64.1.x node Tailscale IPs) for NOTIFY messages
- **VPS rejection**: Secondary zones check NOTIFY source against configured primary IP (10.2.3.3),
  reject messages from other IPs as "not a primary"
- **No fix possible**: Cannot configure all possible node IPs as primaries without breaking DNS delegation
- **Current approach**: AXFR refresh via SOA refresh interval (3 hours) - reliable but not instant
- **Alternatives**: See "DNS Propagation Alternatives" in Research & Evaluation section for faster options

**See**: `docs/archive/axfr_debugging.md` for complete debugging history and solution details

### Storage Evolution

**Rejected**:

- Longhorn V2: High CPU overhead (100% per worker core for SPDK)
- OpenEBS LocalPV: Talos incompatibility (path mount issues)
- Rook-Ceph: Architectural mismatch (requires node-local disks, duplicates ZFS redundancy)

**Current**: Proxmox CSI (RWO only)

- Native ZFS integration (snapshots, checksums, compression)
- Zero worker node CPU overhead
- Simplified architecture via Proxmox API
- Limitation: ReadWriteOnce only (no multi-pod shared storage)

**Future RWX Options**:

1. **NFS StorageClass** (Recommended for current environment)
   - ZFS dataset on tank pool (58TB RAIDZ2) exported via NFS
   - `nfs-subdir-external-provisioner` for dynamic provisioning
   - Leverages existing redundancy (no duplication)
   - Use cases: Media libraries (Jellyfin), shared downloads (qBittorrent), Syncthing
   - Pros: Simple setup, uses tank capacity, native RWX support
   - Cons: Proxmox SPOF (acceptable for single-host setup)

2. **Rook-Ceph** (Only if architecture changes)
   - Requires: Multi-node Proxmox cluster + local disks per worker node
   - Would provide: Distributed HA storage independent of Proxmox
   - Not recommended currently: Centralized storage model mismatch

---

## 🔗 Related Documentation

- **Bootstrap Procedures**: `docs/bootstrap.md`
- **Troubleshooting**: `docs/troubleshooting.md`
- **Operations**: `docs/operations.md`
- **Secret Synchronization**: `docs/archive/SECRET_SYNCHRONIZATION_ANALYSIS.md`
- **Critical Dependencies**: `docs/critical_dependencies.md`
- **Harbor Pull-Through Cache Planning**: `docs/harbor_pullthrough_cache.md`
- **AI Agents Design**: `docs/agents.md` (planned)

---

## 📊 Metrics & Health

**Cluster Status** (2025-12-10):

- Status: Destroyed for rebuild testing (was: 5 nodes, 3 controllers, 2 workers)
- Next: Bootstrap verification with all today's fixes

**SSO Integration Status**:

- ✅ Vault OIDC authentication configured
- ✅ Gitea SSO configured (OAuth dependency fixed)
- ✅ Harbor SSO configured (Terraform resource reference fixed)
- ✅ Matrix/Synapse SSO configured (OIDC via ExternalSecret)
- ✅ Grafana SSO configured (Authentik OIDC)
- ⏳ Pending: Browser testing after bootstrap

**Recent Updates** (2025-12-10):

- Cluster destroyed for rebuild testing
- Fixed Gitea OAuth configuration (10-hour crash loop resolved)
- Implemented Let's Encrypt environment switching capability
- Added RWO volume deployment strategy documentation and protections
- Fixed Harbor SSO Terraform provider configuration
- All documentation reorganized to lowercase naming convention
