# VPS Cluster Integration Plan

**Goal**: Extend the Talos cluster to include a VPS node, creating a geographically distributed
cluster that handles public ingress, DNS, and website hosting directly.

## Current Architecture

```text
Internet → VPS (nginx proxy) → Tailscale VPN → Home Cluster (Proxmox)
                                                    ├── 3 controllers
                                                    └── 3 workers
```

**Current VPS Role** (standalone, not in cluster):

- nginx SNI passthrough proxy
- PowerDNS secondary (AXFR from cluster)
- Tailscale relay for cluster traffic

**Limitations**:

- VPS is a single point of failure for ingress
- PowerDNS on VPS is secondary-only (can't create records directly)
- Website hosting requires separate infrastructure
- No pod scheduling on VPS resources

## Target Architecture

```text
Internet → VPS (2x Talos controller+worker)
              ├── 2 controllers (etcd quorum majority)
              ├── Ingress Controller (receives public traffic)
              ├── PowerDNS (primary for *.agentydragon.com)
              ├── Website pods
              └── KubeSpan mesh (WireGuard) → Home (Proxmox)
                                                   ├── 1 controller
                                                   └── 2+ workers
```

**VPS becomes**:

- 2 Talos controller+worker nodes (dual role)
- Holds etcd quorum majority (2/3) - cluster survives home outage
- Runs ingress-nginx with public IP
- Runs PowerDNS as primary authoritative server
- Hosts website and public-facing services
- Connected to home nodes via **KubeSpan** (Talos native WireGuard mesh)

## Benefits

1. **Unified Management**: Single cluster, single GitOps flow
2. **Geographic Distribution**: Services can run where they make sense
3. **Direct Ingress**: No proxy layer, native Kubernetes ingress
4. **Flexible Scheduling**: Some pods on VPS (public), some at home (storage-heavy)
5. **HA DNS**: PowerDNS can run on multiple nodes
6. **Simplified Architecture**: Remove nginx proxy layer

## Implementation Phases

### Phase 0: Prerequisites

- [ ] **VPS Selection**: New VPS or repurpose existing?
  - Option A: New VPS dedicated to Talos
  - Option B: Migrate existing VPS to Talos (requires downtime)
- [ ] **Network Planning**:
  - VPS public IP for ingress
  - Tailscale mesh connectivity to home nodes
  - Pod CIDR allocation for VPS node
- [ ] **Terraform State Backup**: Set up rclone to Google Drive before major changes
  - [ ] Configure rclone with Google Drive
  - [ ] Create backup script and cron job
  - [ ] Document recovery procedure

### Phase 1: VPS Talos Nodes (2x Controller+Worker)

- [ ] **Provision 2 VPS instances with Talos**
  - Talos image for cloud/VPS (not Proxmox QEMU)
  - Machine config with KubeSpan enabled
  - Controller+worker dual role (schedulable controllers)
- [ ] **Bootstrap New Cluster on VPS**
  - First VPS controller bootstraps cluster
  - Second VPS controller joins
  - Home controller joins (becomes minority)
  - Home workers join
- [ ] **Validate Connectivity**
  - KubeSpan mesh established between all nodes
  - etcd healthy with 3 members (2 VPS + 1 home)
  - Pods on VPS can reach pods at home
  - CoreDNS resolution works across nodes
  - Cilium networking healthy
- [ ] **Test Resilience**
  - Simulate home outage: cluster remains operational
  - Simulate single VPS outage: cluster remains operational

### Phase 2: Migrate Ingress

- [ ] **Deploy ingress-nginx on VPS**
  - Node selector/affinity for VPS node
  - Use VPS public IP (hostNetwork or cloud LB)
  - Configure for public traffic
- [ ] **DNS Cutover**
  - Point *.agentydragon.com to VPS public IP
  - Keep old nginx running as fallback initially
- [ ] **Certificate Management**
  - cert-manager on VPS node
  - DNS-01 challenges (PowerDNS API)
- [ ] **Validate**
  - HTTPS traffic flows through VPS ingress
  - All existing services accessible
  - Decommission old nginx proxy

### Phase 3: Migrate PowerDNS

- [ ] **PowerDNS on VPS Worker**
  - Schedule PowerDNS pods on VPS node
  - Configure as primary authoritative
  - external-dns updates directly
- [ ] **Update DNS Delegation**
  - NS records point to VPS PowerDNS
  - Remove AXFR secondary setup
- [ ] **Validate**
  - DNS queries served from VPS
  - Record creation via external-dns works
  - cert-manager DNS-01 challenges succeed

### Phase 4: Website & Services

- [ ] **agentydragon.com Website**
  - Deploy website pods (static or SSG)
  - Ingress configuration
  - HTTPS via cert-manager
- [ ] **Public Service Migration**
  - Identify services that should run on VPS
  - Configure node affinity/scheduling
  - Update ingress rules
- [ ] **Home-Only Services**
  - Storage-heavy services stay at home (Harbor cache, Vault storage)
  - Configure pod anti-affinity for VPS

### Phase 5: Cleanup & Documentation

- [ ] **Decommission Old VPS Config**
  - Remove nginx proxy Ansible roles
  - Remove PowerDNS secondary config
  - Archive old configurations
- [ ] **Update Documentation**
  - docs/bootstrap.md for multi-node cluster
  - docs/operations.md for VPS node management
  - Architecture diagrams
- [ ] **Monitoring & Alerting**
  - VPS node health monitoring
  - Cross-site latency metrics
  - Alerting for VPS node issues

## Technical Considerations

### Networking: KubeSpan (Talos Native WireGuard)

**Why KubeSpan over Tailscale**:

- **Native to Talos**: No extension required, built into Talos Linux
- **Zero external dependencies**: No Tailscale/Headscale coordination server
- **Automatic mesh**: Full WireGuard mesh between all nodes with automatic key exchange
- **Integrated discovery**: Uses Talos cluster discovery for peer coordination
- **Simpler config**: Just `machine.network.kubespan.enabled: true`

**KubeSpan Configuration**:

```yaml
machine:
  network:
    kubespan:
      enabled: true
      # Optional: allow traffic to bypass KubeSpan if peer is down
      allowDownPeerBypass: false
cluster:
  discovery:
    enabled: true  # Required for KubeSpan
```

**How it works**:

1. Each node gets a WireGuard interface (`kubespan0`)
2. Nodes discover each other via cluster discovery service
3. WireGuard keys are automatically exchanged
4. Full mesh established - all nodes can reach all nodes
5. Only port 51820/udp needs to be open

**Cilium Compatibility**:

- KubeSpan handles node-to-node encryption
- Cilium handles pod networking (IPAM, policy, services)
- For advanced Cilium features (eBPF masquerading), use Cilium's native WireGuard instead

**Public IP Handling**:

- VPS has public IP directly
- ingress-nginx binds to public IP (hostNetwork: true or externalTrafficPolicy)
- MetalLB not needed on VPS (cloud has native LB or direct IP)
- KubeSpan will use VPS public IP as endpoint for other nodes

### Storage

**VPS Storage**:

- Limited local storage on VPS
- No Proxmox CSI (different hypervisor)
- Options: local-path-provisioner, cloud block storage, or no persistent storage

**Home Storage**:

- Proxmox CSI for persistent volumes
- Services needing storage should run at home
- Consider NFS for shared access

### Scheduling

**Node Labels**:

```yaml
# VPS node
topology.kubernetes.io/zone: vps
node.kubernetes.io/instance-type: vps

# Home nodes
topology.kubernetes.io/zone: home
node.kubernetes.io/instance-type: proxmox-vm
```

**Pod Placement Examples**:

```yaml
# Public services on VPS
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: topology.kubernetes.io/zone
          operator: In
          values: [vps]

# Storage services at home
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: topology.kubernetes.io/zone
          operator: In
          values: [home]
```

### Failure Modes

**Single VPS Node Outage**:

- ✅ Cluster operational (2/3 controllers remain: 1 VPS + 1 home)
- ✅ Public ingress continues on remaining VPS node
- ✅ PowerDNS continues serving
- Mitigation: Pod anti-affinity for critical services across VPS nodes

**Both VPS Nodes Down** (full VPS outage):

- ❌ Cluster control plane down (only 1/3 controllers)
- ❌ Public ingress unavailable
- ❌ DNS queries fail
- Existing pods at home continue running but can't be managed
- Recovery: Restore VPS connectivity

**Home Outage**:

- ✅ Cluster operational (2/3 controllers on VPS)
- ✅ Public ingress continues
- ✅ DNS continues
- ✅ Website serves static content
- ❌ SSO (Authentik at home)
- ❌ Internal services (Harbor, Gitea, Grafana, Vault, media)
- Recovery: Restore home connectivity

**KubeSpan Outage** (WireGuard mesh failure):

- Cross-site pod communication fails
- VPS can still serve stateless/cached content
- etcd may have issues if cross-site latency spikes
- Home pods continue running independently

## Decisions

1. **New VPS: 2x Hetzner Cloud CPX31 in Hillsboro, OR**
   - Names: `ubuntu-8gb-hil-1`, `ubuntu-8gb-hil-2` (pre-Talos)
   - 4 vCPU, 8GB RAM, 160GB NVMe each
   - ~$34/month total for both nodes
   - ~15-25ms latency to SF (acceptable for etcd)
   - SSH access: pubkey from wyrm VM
   - Backups enabled
   - Old VPS remains operational until cutover

2. **Controller placement: 2 VPS + 1 home (3 total)**
   - Survives home outage (2/3 quorum on VPS)
   - Accepts VPS as more critical than home for control plane
   - Tradeoff: etcd latency (20-100ms cross-internet), but acceptable for resilience
   - Alternative considered: 3 VPS + 2 home (5 total) - more resources, same resilience

3. **Big-bang migration** - Cleaner cutover, single downtime window, less complexity than gradual

## Storage Strategy

**Goal**: Public-facing services survive home outage with their own storage on VPS.

### VPS Storage (small, independent)

- **Provisioner**: local-path-provisioner or cloud block storage
- **Capacity**: ~50-100GB per VPS node (enough for critical services)
- **Services** (no SSO required):
  - PowerDNS database (~1GB)
  - Website content (static, ~1GB)
  - cert-manager state

### Home Storage (large array)

- **Provisioner**: Proxmox CSI backed by ZFS
- **Capacity**: Multi-TB array (RAIDZ2)
- **Services**:
  - Authentik + PostgreSQL (SSO for internal services)
  - Harbor registry cache (100GB+)
  - Media services (Jellyfin, *arr stack)
  - Vault storage
  - Backups
  - Nix cache
  - Gitea, Grafana, etc.

### Scheduling Implications

```yaml
# Public-facing: must run on VPS, use VPS storage
nodeAffinity: vps
storageClass: local-path  # or cloud-block

# Storage-heavy: must run at home, use Proxmox CSI
nodeAffinity: home
storageClass: proxmox-csi
```

**Home outage impact**: Internal services (SSO, registry, media, Vault) unavailable.
Public-facing services (website, DNS) continue on VPS.

## Related Tasks

From todo list:

- [ ] Set up rclone with Google Drive (terraform state backup)
- [ ] Create backup script and cron
- [ ] Update NixOS hosts with nix-cache key

## References

- Current cluster: `docs/plan.md`
- Bootstrap procedure: `docs/bootstrap.md`
- Talos documentation: <https://www.talos.dev/>
- Cilium multi-cluster: <https://docs.cilium.io/en/stable/network/clustermesh/>
