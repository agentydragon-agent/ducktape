# VPS Cluster Integration

**Status**: Fully integrated hybrid cluster (VPS + Proxmox)

## Architecture

```text
Internet → VPS (2x Hetzner CPX31)
              ├── 2 Talos control-plane nodes (public IPs)
              ├── ingress-nginx + PowerDNS (hostNetwork)
              ├── Hetzner Cloud CSI (Flux-managed)
              └── KubeSpan mesh (WireGuard) → Home Proxmox (atlas)
                                                  └── 1 Talos control-plane (10.2.1.1)
                                                      └── Proxmox CSI (ZFS storage)
```

## Nodes

| Node           | Location | Role          | IP            |
| -------------- | -------- | ------------- | ------------- |
| talos-vps-cp-0 | Hetzner  | control-plane | (new on boot) |
| talos-vps-cp-1 | Hetzner  | control-plane | (new on boot) |
| talos-pve-cp-0 | Proxmox  | control-plane | 10.2.1.1      |

## Networking

### KubeSpan (WireGuard Mesh)

Talos-native WireGuard mesh connecting VPS and home nodes.

- Enabled in Talos machine config (`machine.network.kubespan.enabled: true`)
- Discovery via `discovery.talos.dev`
- Machine secrets regenerated per lifecycle (fresh `cluster.id` prevents stale peers)
- Requires UDP 51820 open on all nodes

### Cilium CNI

- VXLAN tunnel mode (VPS nodes not on same L2)
- `MTU: 1370` (uppercase key, case-sensitive) — accounts for VXLAN (50) + WireGuard (80) overhead
- `kubeProxyReplacement: true`

### Ingress

```text
Internet → VPS public IP:443 → ingress-nginx (hostNetwork) → backend services
Internet → VPS public IP:53  → PowerDNS (hostNetwork) → DNS responses
```

DNS returns two A records (both VPS IPs) for failover.

## Storage

| Provisioner          | Location | Default | Management                         |
| -------------------- | -------- | ------- | ---------------------------------- |
| `proxmox-csi-retain` | Proxmox  | Yes     | Flux (k8s/storage/)                |
| `hcloud-volumes`     | Hetzner  | No      | Flux (k8s/hcloud-csi/)             |
| `local-path`         | Any node | No      | Flux (k8s/local-path-provisioner/) |

**Strategy**: Proxmox for storage-heavy workloads (Harbor, Gitea, Loki, media, Nix cache).
VPS for always-on critical-path services. `local-path` for simple storage (Vault Raft, Headscale).

## Failure Modes

| Scenario        | Cluster    | Ingress | Notes                                 |
| --------------- | ---------- | ------- | ------------------------------------- |
| Single VPS down | 2/3 quorum | Works   | DNS failover to other VPS             |
| Both VPS down   | 1/3 only   | Down    | Home pods continue but cluster frozen |
| Home down       | 2/3 quorum | Works   | Proxmox storage workloads unavailable |

## Decisions

1. **2x Hetzner CPX31** — 4 vCPU, 8GB RAM, 160GB NVMe, ~EUR 30/month total
2. **Controller placement: 2 VPS + 1 home** — survives home outage, etcd majority on VPS
3. **KubeSpan over Tailscale** — native to Talos, no external dependencies
4. **Cilium VXLAN** — required for cross-VPS networking (nodes not on same L2)
5. **Hetzner CSI via Flux** — API token secret created by infrastructure terraform, chart managed by Flux
