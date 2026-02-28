# Roaming Laptop Worker Node

Join a regular Linux desktop/laptop to the Talos cluster as a worker without VMs.

## Architecture

```text
┌──────────────────────────────┐
│  Linux Desktop (NixOS)       │
│  ├── desktop environment     │
│  ├── containerd + kubelet    │
│  ├── Tailscale → Headscale   │
│  ├── HAProxy (localhost:7445)│
│  └── Cilium agent (DaemonSet)│
└──────────────────────────────┘
         │ Tailscale mesh (UDP 41641)
         ▼
┌──────────────────────────────┐    ┌──────────────────────────────┐
│  VPS nodes (Hetzner)         │    │  Proxmox K8s nodes           │
│  ├── Tailscale DaemonSet ◄───┤    │  ├── Tailscale DaemonSet ◄───┤
│  └── public IP (direct)      │    │  └── 10.2.x.x (via atlas)   │
└──────────────────────────────┘    └──────────────────────────────┘
                                             │ direct LAN
                                             ▼
                                    ┌──────────────────────────────┐
                                    │  atlas (Proxmox host)        │
                                    │  └── Tailscale (advertises   │
                                    │      10.2.0.0/16 subnet)     │
                                    └──────────────────────────────┘
```

All cluster nodes run a Tailscale DaemonSet (`k8s/tailscale/`) connecting to the
in-cluster Headscale at `headscale.allegedly.works`. This creates a second WireGuard
mesh alongside KubeSpan, enabling roaming devices to reach every node.

VPS nodes are also reachable via public IPs (direct). Proxmox nodes (10.2.x.x) are
reachable via atlas advertising `10.2.0.0/16` as a Headscale subnet route.

## Prerequisites

- **Tailscale DaemonSet deployed**: `k8s/tailscale/` must be reconciled and all node
  pods running. Verify: `kubectl get ds tailscale -n tailscale`
- **Atlas advertising subnet route**: atlas must have Tailscale running with
  `--advertise-routes=10.2.0.0/16` and the route approved in Headscale

## Motivation

- Extra CPU (and optionally GPU) capacity for batch/ephemeral workloads
- BuildBuddy remote executors, CI runners, ML jobs
- No VM overhead — full hardware access, desktop stays usable

## Networking

### Two WireGuard Meshes

| Mesh      | Port      | Interface    | Purpose                          |
| --------- | --------- | ------------ | -------------------------------- |
| KubeSpan  | UDP 51820 | `kubespan`   | Intra-cluster (Talos nodes only) |
| Tailscale | UDP 41641 | `tailscale0` | Roaming device access            |

Different ports, keys, and routing tables — no conflict. KubeSpan handles all
cluster bootstrap networking. Tailscale is purely additive.

### Traffic Flows

| Source → Dest          | Path                                         |
| ---------------------- | -------------------------------------------- |
| Laptop → VPS           | Public IP (direct) or Tailscale              |
| Laptop → Proxmox nodes | Tailscale → atlas subnet route (10.2.0.0/16) |
| VPS → Laptop           | Tailscale (100.64.x.x via `tailscale0`)      |
| Proxmox → Laptop       | Tailscale (100.64.x.x via `tailscale0`)      |

### Headscale Dependency

Headscale runs inside the cluster (on VPS nodes). Failure modes:

- **Headscale down, tunnel already established**: Tunnel stays up (peer-to-peer WireGuard).
  Can't discover new peers or rotate keys, but existing connectivity works.
- **Headscale down, laptop was offline**: Can't reconnect until Headscale comes back.
  Laptop still reaches VPS nodes directly (public IPs), so kubelet stays connected
  to the API server. Pods can't talk to Proxmox-hosted pods.
- **DNS down**: Can't resolve `headscale.allegedly.works`. Mitigate by hardcoding
  the Headscale IP in Tailscale config.

### Why Not Static WireGuard?

KubeSpan doesn't support static/extra peers. Talos nodes only accept WireGuard peers
discovered through the discovery service (`discovery.talos.dev`). A manually configured
WireGuard peer won't be in the Talos nodes' peer list, so they'll ignore handshake
attempts.

## Implementation

### NixOS Module

A NixOS module at `nix/nixos/modules/k8s-worker.nix` configures the machine as a K8s
worker. It does NOT use `services.kubernetes` (too opinionated toward all-NixOS clusters).

Components:

- **containerd** with systemd cgroup driver
- **kubelet** as a custom systemd service (TLS bootstrap, not auto-started)
- **HAProxy** at `localhost:7445` → `api.allegedly.works` (replaces Talos KubePrism)
- **Tailscale** configured for Headscale with `--accept-routes`
- **Kernel prereqs**: `overlay`, `br_netfilter`, IP forwarding
- **Firewall**: VXLAN (UDP 8472), kubelet (TCP 10250)

Key design decisions:

- **CNI path**: containerd points `cni.bin_dir` to `/opt/cni/bin`. Cilium's DaemonSet
  installs `cilium-cni` and `loopback` there at runtime. No Nix-side CNI plugins needed.
- **`mount` wrapper**: kubelet's PATH prepends `/run/wrappers/bin` for NixOS setuid
  `mount`/`umount` (needed for projected/tmpfs volumes).
- **`--node-ip` from Tailscale**: `ExecStartPre` resolves the Tailscale IPv4 via
  `tailscale ip --4` and passes it as `--node-ip`. Kubelet won't start until Tailscale
  is connected.
- **Tailscale DaemonSet conflict**: The NixOS node runs Tailscale natively via
  `services.tailscale`. The cluster's Tailscale DaemonSet also schedules on this node
  and conflicts over `/dev/net/tun`. Needs resolution (node label exclusion or
  DaemonSet affinity).

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
   # Keep server as https://127.0.0.1:7445 — HAProxy handles routing to control plane
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
and labels `topology.kubernetes.io/region=roaming`, `node.kubernetes.io/role=roaming`.

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
- **Kubelet label restrictions**: Labels in `node-role.kubernetes.io/*` are NOT allowed
  via `--node-labels` (kubelet rejects them as restricted). Use `node.kubernetes.io/role`
  instead. The taint `node-role.kubernetes.io/roaming=true:NoSchedule` is fine (taints
  don't have the same restriction).
- **K8s version skew**: NixOS `pkgs.kubernetes` may lag behind the cluster version.
  Check `kubelet --version` vs `kubectl version` — must be within 1 minor version.

## Current Status

**Tailscale DaemonSet**: Deployed and running on all 4 cluster nodes. Nodes registered in
Headscale, peer discovery working. Direct peer-to-peer connections established (UDP 41641
open on Hetzner firewall).

**kubelet `validSubnets`**: Applied. Nodes will not register with Tailscale CGNAT IPs.

**Mesh connectivity verified from wyrm** (2026-02-27): All 4 cluster nodes reachable via
Tailscale IPs. Latency: VPS ~55-65ms, Proxmox ~54ms. Stages 1-2 complete.

**k8s-worker-test VM joined** (2026-02-27): NixOS test VM (Proxmox VM 111) successfully
joined the cluster as a worker node. Bootstrap kubeconfig extracted from Talos, CSR approved.
Node visible in `kubectl get nodes` as Ready. Cilium agent running, test pod scheduled and
running with pod IP.

**Remaining issues** (2026-02-27):

- `kubectl exec` fails — API server can't reach kubelet at the node's LAN IP (`10.0.53.87`).
  Fix committed: kubelet now resolves `--node-ip` from Tailscale IP via `ExecStartPre`.
  Needs VM rebuild + node re-registration to take effect.
- Tailscale DaemonSet conflicts with native Tailscale on NixOS nodes (both want `/dev/net/tun`).
  Needs DaemonSet nodeAffinity or label-based exclusion.
- `node-feature-discovery` CrashLoopBackOff on the NixOS node (non-critical).

## Next Test Stages

### Stage 1: Verify Tailscale Mesh Health

From a machine already registered with Headscale (or register a test device first):

```bash
# Check all cluster nodes are visible in Headscale
kubectl exec -n headscale deployment/headscale -- headscale nodes list

# From a Headscale-connected device, ping each node's Tailscale IP
tailscale status  # shows peer list with IPs
ping <node-tailscale-ip>
```

Verify:

- [x] All 4 cluster nodes appear in `headscale nodes list`
- [x] Tailscale IPs (100.64.x.x) are reachable from a connected device
- [x] Direct peer connections establish (not just DERP relay) — all 4 direct

### Stage 2: Register a Laptop with Headscale

On the laptop (NixOS or any Linux):

```bash
# Install Tailscale
sudo tailscale up --login-server=https://headscale.allegedly.works

# Approve in Headscale (from cluster)
kubectl exec -n headscale deployment/headscale -- \
  headscale nodes list  # find the pending node
kubectl exec -n headscale deployment/headscale -- \
  headscale nodes approve <node-id>  # or register via pre-auth key
```

Verify:

- [x] Laptop gets a 100.64.x.x IP (wyrm: 100.64.0.1)
- [x] Laptop can ping all cluster node Tailscale IPs
- [x] Cluster nodes can ping laptop's Tailscale IP
- [x] `--accept-routes` enabled (`RouteAll: true`); atlas subnet route N/A from LAN

### Stage 3: Test L3 Connectivity for VXLAN

The laptop worker needs L3 connectivity to all nodes for Cilium VXLAN (UDP 8472).

```bash
# From laptop, test VXLAN port reachability to each node
for ip in <vps0-tailscale-ip> <vps1-tailscale-ip> <pve-cp0-tailscale-ip> <pve-gpu-tailscale-ip>; do
  nc -zuv $ip 8472 2>&1
done

# Also test kubelet API port
for ip in <node-ips>; do
  curl -k https://$ip:10250/healthz 2>&1
done
```

Verify:

- [ ] UDP 8472 reachable from laptop to all nodes via Tailscale
- [ ] TCP 10250 reachable from all nodes to laptop (for kubelet API)
- [ ] TCP 6443 reachable from laptop to control plane (for API server)

### Stage 4: Join Test VM as Worker Node

Tested with `k8s-worker-test` VM (Proxmox VM 111). Key sequence:

1. Extract bootstrap kubeconfig + CA cert from Talos
2. Copy to VM, HAProxy already configured via NixOS module
3. Start kubelet, approve CSR
4. Verify node appears in `kubectl get nodes`
5. Deploy a test pod with roaming toleration, verify it schedules and runs

Verify:

- [x] Node appears in `kubectl get nodes` as Ready
- [x] Cilium agent runs on the node (DaemonSet pod healthy)
- [x] Test pod with roaming toleration schedules on the node
- [ ] `kubectl exec` works (blocked: node IP must be Tailscale IP, not LAN IP)

### Stage 5: End-to-End Workload Test

```bash
# Deploy a test pod that tolerates the roaming taint
kubectl run test-roaming --image=busybox --restart=Never \
  --overrides='{
    "spec": {
      "tolerations": [{"key": "node-role.kubernetes.io/roaming", "operator": "Exists"}],
      "nodeSelector": {"node.kubernetes.io/role": "roaming"},
      "containers": [{"name": "test", "image": "busybox", "command": ["sleep", "3600"]}]
    }
  }'

# Verify cross-node pod connectivity (from test pod to a VPS-hosted pod)
kubectl exec test-roaming -- wget -qO- http://<cluster-service>.<namespace>.svc.cluster.local
```

Verify:

- [x] Pod schedules on laptop node
- [ ] Pod-to-pod networking works (VXLAN over Tailscale)
- [ ] DNS resolution works inside pods on the laptop node
- [ ] Pod-to-service networking works (ClusterIP routing)

### Stage 6: Resilience Testing

- [ ] Laptop sleep/wake: node goes `NotReady`, pods evicted after 5min, recovers on wake
- [ ] Network change (WiFi→Ethernet): Tailscale reconnects, node recovers
- [ ] Headscale restart: existing tunnels survive, laptop reconnects after Headscale is back

## Open Questions

- **GPU sharing**: If the laptop has a GPU, it's available to both desktop and cluster
  workloads natively (no VFIO). Contention risk: desktop compositor vs CUDA jobs.
  May need cgroup isolation or manual coordination.
- **Atlas Tailscale setup**: atlas needs Tailscale installed and advertising subnet
  routes. This is a prerequisite not yet automated.
- **CSR auto-approval**: Consider deploying a CSR approver controller to avoid manual
  `kubectl certificate approve` on every node join.

### HAProxy Control Plane Endpoint Management

**Resolved**: HAProxy now resolves `api.allegedly.works` via DNS at runtime using
`server-template` with a `resolvers` section. The DNS record (managed by Terraform in
`cluster/terraform/gitops/dns-records/main.tf`) round-robins across VPS public IPs.

**Why HAProxy exists**: Cilium is configured cluster-wide with `k8sServiceHost: localhost`,
`k8sServicePort: 7445`. On Talos nodes, KubePrism (built into `machined`) provides this.
On non-Talos nodes, nothing listens there without a local proxy. KubePrism is not a
standalone binary.

The Proxmox CP (`10.2.1.1`) is excluded — it has no public IP, and if both VPS nodes are
down, Headscale is also down so the NixOS worker would be offline regardless. 2/3 CPs is
sufficient for API access.

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
