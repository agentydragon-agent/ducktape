# Roaming Laptop Worker Node

Join a regular Linux desktop/laptop to the Talos cluster as a worker without VMs.

## Architecture (Recommended: Headscale)

```text
┌──────────────────────────────┐
│  Linux Desktop (NixOS)       │
│  ├── desktop environment     │
│  ├── containerd + kubelet    │
│  ├── Tailscale → Headscale   │
│  ├── HAProxy (localhost:7445)│
│  └── Cilium agent (DaemonSet)│
└──────────────────────────────┘
         │ Tailscale mesh
         ▼
┌──────────────────────────────┐
│  atlas (Proxmox host)        │
│  └── Tailscale (advertises   │
│      10.2.0.0/16 subnet)     │
└──────────────────────────────┘
         │ direct LAN
         ▼
   Proxmox cluster nodes (10.2.x.x)

VPS nodes reached directly via public IPs.
```

## Motivation

- Extra CPU (and optionally GPU) capacity for batch/ephemeral workloads
- BuildBuddy remote executors, CI runners, ML jobs
- No VM overhead — full hardware access, desktop stays usable

## Networking Options Comparison

| Option                      | Roaming                       | Build effort        | Durability        | NAT traversal   |
| --------------------------- | ----------------------------- | ------------------- | ----------------- | --------------- |
| **Headscale (recommended)** | Full                          | Trivial             | Survives rebuilds | Yes (DERP)      |
| Custom kubespan-agent       | Full                          | ~weekend Go project | Survives rebuilds | Yes (discovery) |
| Static WireGuard            | N/A                           | N/A                 | N/A               | N/A             |
| VPS WireGuard tunnel        | Full                          | Trivial             | Durable           | Manual          |
| Direct IP only              | Partial (VPS yes, Proxmox no) | None                | Durable           | No              |

### Why Not Static WireGuard?

KubeSpan doesn't support static/extra peers. Talos nodes only accept WireGuard peers
discovered through the discovery service (`discovery.talos.dev`). A manually configured
WireGuard peer won't be in the Talos nodes' peer list, so they'll ignore handshake
attempts. This rules out static WireGuard as an option.

### Why Headscale?

- Already deployed in the cluster at `headscale.allegedly.works`
- Tailscale data plane is peer-to-peer WireGuard — established tunnels survive
  Headscale downtime
- NAT traversal via DERP relays (Tailscale's external DERP servers, no cluster dependency)
- Independent of KubeSpan/Talos machine secrets — doesn't break on cluster rebuild
- atlas (Proxmox host) can advertise `10.2.0.0/16` as a subnet route, giving the
  laptop connectivity to all Proxmox nodes

### Headscale Dependency

Headscale runs inside the cluster (on VPS nodes). Failure modes:

- **Headscale down, tunnel already established**: Tunnel stays up (peer-to-peer WireGuard).
  Can't discover new peers or rotate keys, but existing connectivity works.
- **Headscale down, laptop was offline**: Can't reconnect until Headscale comes back.
  Laptop still reaches VPS nodes directly (public IPs), so kubelet stays connected
  to the API server. Pods can't talk to Proxmox-hosted pods.
- **DNS down**: Can't resolve `headscale.allegedly.works`. Mitigate by hardcoding
  the Headscale IP in Tailscale config.

### Custom KubeSpan Agent (Alternative)

Build a Go daemon that implements the Talos discovery protocol to join the KubeSpan
WireGuard mesh natively. ~500-1000 lines wrapping the existing
[`siderolabs/discovery-client`](https://github.com/siderolabs/discovery-client) library.
Reference: `internal/app/machined/pkg/controllers/kubespan/` in the
[Talos source](https://github.com/siderolabs/talos).

See [KubeSpan internals](#appendix-kubespan-internals) appendix for full details.

## Implementation

### NixOS Module

A NixOS module at `nix/nixos/modules/k8s-worker.nix` configures the machine as a K8s
worker. It does NOT use `services.kubernetes` (too opinionated toward all-NixOS clusters).

Components:

- **containerd** with systemd cgroup driver
- **kubelet** as a custom systemd service (TLS bootstrap, not auto-started)
- **HAProxy** at `localhost:7445` → control plane (replaces Talos KubePrism)
- **Tailscale** configured for Headscale with `--accept-routes`
- **Kernel prereqs**: `overlay`, `br_netfilter`, IP forwarding
- **Firewall**: VXLAN (UDP 8472), kubelet (TCP 10250)

Module options under `ducktape.k8sWorker`:

- `enable`, `controlPlaneEndpoints`, `clusterDNS`, `headscaleUrl`, `caCertPath`,
  `nodeLabels`, `nodeTaints`

### Test VM

A Proxmox VM (`k8s-worker-test`, VM ID 111) in `terraform/nixos-dev-env/` uses
the `k8s-worker-test` NixOS host config (GNOME desktop + k8s-worker module).

### Manual Steps After Boot

1. **Extract bootstrap kubeconfig** from Talos:
   ```bash
   talosctl -n <vps-ip> cat /etc/kubernetes/bootstrap-kubeconfig > bootstrap-kubelet.conf
   talosctl -n <vps-ip> cat /etc/kubernetes/pki/ca.crt > ca.crt
   sed -i 's|https://localhost:7445|https://<vps-ip>:6443|g' bootstrap-kubelet.conf
   ```
2. **Copy to the machine**:
   ```bash
   scp bootstrap-kubelet.conf ca.crt user@<vm-ip>:/tmp/
   ssh user@<vm-ip> 'sudo mkdir -p /etc/kubernetes/pki && \
     sudo cp /tmp/ca.crt /etc/kubernetes/pki/ && \
     sudo cp /tmp/bootstrap-kubelet.conf /etc/kubernetes/'
   ```
3. **Register with Headscale** (on the machine):
   ```bash
   sudo tailscale up --login-server=https://headscale.allegedly.works
   # Approve the node in Headscale admin
   ```
4. **On atlas**: ensure Tailscale is running and advertising `10.2.0.0/16`
5. **Start kubelet**: `sudo systemctl start kubelet`
6. **Approve CSR** on the cluster:
   ```bash
   kubectl get csr
   kubectl certificate approve <csr-name>
   ```

## Scheduling

The node registers with taint `node-role.kubernetes.io/roaming=true:NoSchedule`
and labels `topology.kubernetes.io/region=roaming`, `node-role.kubernetes.io/roaming=true`.

**Good fit** (tolerates interruption):

- BuildBuddy remote executors
- Batch ML/LLM jobs
- CI runners
- Dev/test workloads

**Avoid** (needs persistent availability):

- StatefulSets, databases, PVCs
- Anything in the VPS-only resilience invariant list
- Ingress or service mesh components

## Intermittent Connectivity

When the laptop sleeps or changes networks:

- Node goes `NotReady` after ~40s (`node-monitor-grace-period`)
- Pods evicted after 5 minutes (default `tolerationSeconds`)

Mitigations:

- Taint (`NoSchedule`) ensures only opt-in workloads land there
- Increase `tolerationSeconds` on workloads that can handle brief disconnects
- No PVCs — stateless workloads only

## Known Gotchas

- **KubePrism**: Cilium is configured with `k8sServiceHost: localhost`,
  `k8sServicePort: 7445`. Non-Talos nodes don't have KubePrism — HAProxy fills this role.
- **Cilium `SYS_MODULE`**: Talos drops this capability from Cilium pods. On a regular
  Linux box, Cilium may need to load kernel modules. Pre-load `sch_ingress` etc. or
  adjust via `CiliumNodeConfig`.
- **Kubelet version**: Must match the cluster's K8s version (or be within version skew policy).
  No automated upgrades — manual update when the cluster's K8s version changes.
- **No `talosctl`**: Debugging uses SSH and standard Linux tools, not `talosctl`.

## Open Questions

- **GPU sharing**: If the laptop has a GPU, it's available to both desktop and cluster
  workloads natively (no VFIO). Contention risk: desktop compositor vs CUDA jobs.
  May need cgroup isolation or manual coordination.
- **Atlas Tailscale setup**: atlas needs Tailscale installed and advertising subnet
  routes. This is a prerequisite not yet automated.
- **CSR auto-approval**: Consider deploying a CSR approver controller to avoid manual
  `kubectl certificate approve` on every node join.

## Appendix: KubeSpan Internals

KubeSpan is Talos-specific (no standalone client — confirmed by Sidero Labs in
[discussion #10032](https://github.com/siderolabs/talos/discussions/10032)).

Under the hood: standard WireGuard + nftables packet marking + gRPC discovery:

| Component           | Detail                                                                       |
| ------------------- | ---------------------------------------------------------------------------- |
| WireGuard interface | `kubespan`, UDP 51820, full mesh                                             |
| Discovery           | gRPC to `discovery.talos.dev:443`, encrypted with `cluster.secret` (AES-GCM) |
| Packet marking      | nftables table `talos_kubespan`, fwmark `0x40`/`0x20`, mask `0x60`           |
| Routing             | Table 180, ip rule at priority 32500                                         |
| Addressing          | Deterministic IPv6 ULA from `cluster.id` + first NIC MAC                     |
| Peer state          | Endpoint cycling on down detection (275s handshake timeout)                  |

`cluster.id` and `cluster.secret` come from Talos machine secrets and regenerate on
each cluster lifecycle (`tofu destroy` → bootstrap).
