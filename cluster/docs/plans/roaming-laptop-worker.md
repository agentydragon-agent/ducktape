# Roaming Laptop Worker Node

Join a regular Linux desktop/laptop to the Talos cluster as a worker without VMs.

## Architecture

```text
┌──────────────────────────────┐
│  Linux Desktop (NixOS)       │
│  ├── desktop environment     │
│  ├── containerd + kubelet    │
│  ├── kubespand (KubeSpan)    │
│  ├── HAProxy (localhost:7445)│
│  └── Cilium agent (DaemonSet)│
└──────────────────────────────┘
         │ KubeSpan mesh (UDP 51820)
         ▼
┌──────────────────────────────┐    ┌──────────────────────────────┐
│  VPS nodes (Hetzner)         │    │  Proxmox K8s nodes           │
│  └── KubeSpan (native Talos) │    │  └── KubeSpan (native Talos) │
└──────────────────────────────┘    └──────────────────────────────┘
```

Single mesh. NixOS worker joins the Talos KubeSpan WireGuard mesh directly via kubespand
(our standalone KubeSpan daemon). Same fabric as Talos nodes — no second mesh, no Tailscale
DaemonSet dependency.

## Prerequisites

- kubespand binary (CI-built, fetched via Nix `fetchurl` from GitHub Releases)
- Cluster credentials (`cluster.id` and `cluster.secret` from Talos machine config)

## Motivation

- Extra CPU (and optionally GPU) capacity for batch/ephemeral workloads
- BuildBuddy remote executors, CI runners, ML jobs
- No VM overhead — full hardware access, desktop stays usable
- Uniform connectivity model — same KubeSpan mesh as all other nodes

## Networking

### Single KubeSpan Mesh

| Property       | Value                                    |
| -------------- | ---------------------------------------- |
| Port           | UDP 51820                                |
| Interface      | `kubespan`                               |
| Discovery      | `discovery.talos.dev:443` (gRPC)         |
| Encryption     | WireGuard + AES-GCM (discovery)          |
| Addressing     | IPv6 ULA derived from `cluster.id` + MAC |
| Packet marking | nftables fwmark `0x40`/`0x60`            |
| Routing        | Table 180, ip rule at priority 32500     |
| Peer state     | 275s handshake timeout, endpoint cycling |

### Node IP = KubeSpan ULA

The kubelet's `--node-ip` is the KubeSpan ULA IPv6 address (assigned to the `kubespan`
WireGuard interface). This address is:

- **Automatically routed** by all KubeSpan peers (in AllowedIPs as /128)
- **Stable** across network changes (derived from `cluster.id` + MAC)
- **Requires no kubespand changes** (no need to advertise real IPs)

**Risk**: Existing Talos nodes have IPv4 node-ips. Adding an IPv6 node creates mixed
VTEP addresses in the Cilium VXLAN mesh. If Cilium doesn't handle it, fall back to
advertising the real IP via a new kubespand `node_addresses` config field.

### Traffic Flows

| Source → Dest          | Path                                      |
| ---------------------- | ----------------------------------------- |
| Laptop → any node      | KubeSpan WireGuard mesh (UDP 51820)       |
| Any node → Laptop      | KubeSpan WireGuard mesh (UDP 51820)       |
| Pod → Pod (cross-node) | VXLAN (UDP 8472) encapsulated in KubeSpan |

### Discovery Service Dependency

The discovery service (`discovery.talos.dev:443`) is external to the cluster.
Failure modes:

- **Discovery down, peers already known**: Existing WireGuard tunnels continue.
  Can't discover new peers or update endpoints.
- **Discovery down, kubespand just started**: Can't find peers. Will retry
  continuously until discovery is reachable.

## Implementation

### NixOS Modules

**`nix/nixos/modules/kubespand.nix`**: Standalone NixOS module for the kubespand daemon.
Manages systemd service, WireGuard kernel module, firewall, IPv6 forwarding. Config file
(`/etc/kubespan/agent.yaml`) contains secrets and must be placed manually.

**`nix/nixos/modules/k8s-worker.nix`**: K8s worker module with `fabric` option:

| Option   | Values                      | Default       |
| -------- | --------------------------- | ------------- |
| `fabric` | `"tailscale"`, `"kubespan"` | `"tailscale"` |

When `fabric = "kubespan"`:

- Enables `ducktape.kubespand`
- kubelet has `Requires=kubespand.service` + `After=kubespand.service`
- `ExecStartPre` reads ULA from the `kubespan` interface (no polling — interface
  is already up due to systemd dependency)
- No Tailscale service configured

When `fabric = "tailscale"`: existing Headscale/Tailscale behavior (legacy).

Components (both fabrics):

- **containerd** with systemd cgroup driver
- **kubelet** as a custom systemd service (TLS bootstrap, not auto-started)
- **HAProxy** at `localhost:7445` → `api.allegedly.works` (replaces Talos KubePrism)
- **Kernel prereqs**: `overlay`, `br_netfilter`, IP forwarding
- **Firewall**: VXLAN (UDP 8472), kubelet (TCP 10250)

### CI Release

`.github/workflows/kubespand-release.yml` builds kubespand via Bazel, creates GitHub
releases, and auto-updates the Nix package hash in `nix/nixos/packages/kubespand.nix`.

### Test VM

A Proxmox VM (`k8s-worker-test`, VM ID 111) in `terraform/nixos-dev-env/` uses
the `k8s-worker-test` NixOS host config (GNOME desktop + k8s-worker with kubespan fabric).

## Test Stages

### Stage 1: Deploy kubespand

kubespand binary comes from CI-built GitHub release (fetched via Nix `fetchurl`
in `nix/nixos/packages/kubespand.nix`). Deployed automatically via NixOS config.

For iterative development, override with local build:

```bash
bazel build //cluster/kubespand:kubespand
scp bazel-bin/cluster/kubespand/kubespand_/kubespand user@<vm>:/tmp/
ssh user@<vm> 'sudo cp /tmp/kubespand /usr/local/bin/ && sudo systemctl restart kubespand'
```

### Stage 2: Configure and Start kubespand

```bash
# Extract secrets from Talos
CLUSTER_ID=$(talosctl -n <cp-ip> get machineconfiguration -o yaml | yq '.spec.cluster.id')
CLUSTER_SECRET=$(talosctl -n <cp-ip> get machineconfiguration -o yaml | yq '.spec.cluster.secret')

# Create config on VM
sudo mkdir -p /etc/kubespan
sudo tee /etc/kubespan/agent.yaml <<EOF
cluster:
  id: "$CLUSTER_ID"
  secret: "$CLUSTER_SECRET"

kubernetes:
  advertise_networks: true
  kubeconfig_path: "/var/lib/kubelet/kubelet.conf"
  node_name: "k8s-worker-test"
  service_cidrs:
    - "10.96.0.0/12"
EOF
sudo chmod 600 /etc/kubespan/agent.yaml

sudo systemctl start kubespand
```

### Stage 3: Verify KubeSpan Mesh

```bash
# On NixOS node
wg show kubespan                    # peers with recent handshakes
ip rule show | grep 32500           # policy routing rule exists
ip route show table 180             # routes via kubespan

# From a Talos node
talosctl -n <vps-ip> get kubespanpeerstatuses  # NixOS peer shows "up"
```

Verify:

- [ ] `wg show kubespan` shows peers with recent handshakes
- [ ] `ip rule show` has fwmark-based rule at priority 32500
- [ ] `ip route show table 180` shows routes via kubespan interface
- [ ] From Talos: `talosctl get kubespanpeerstatuses` shows NixOS peer as "up"

### Stage 4: Join as K8s Worker

```bash
# Extract bootstrap kubeconfig + CA
talosctl -n <cp-ip> cat /etc/kubernetes/bootstrap-kubeconfig > bootstrap-kubelet.conf
talosctl -n <cp-ip> cat /etc/kubernetes/pki/ca.crt > ca.crt
# Keep server as https://127.0.0.1:7445 — HAProxy handles routing to control plane

# Copy to VM
scp bootstrap-kubelet.conf ca.crt user@<vm-ip>:/tmp/
ssh user@<vm-ip> 'sudo mkdir -p /etc/kubernetes/pki && \
  sudo cp /tmp/ca.crt /etc/kubernetes/pki/ && \
  sudo cp /tmp/bootstrap-kubelet.conf /etc/kubernetes/'

# Start kubelet
ssh user@<vm-ip> 'sudo systemctl start kubelet'

# Approve CSR
kubectl get csr
kubectl certificate approve <csr-name>
```

Verify:

- [ ] Node appears in `kubectl get nodes` as Ready
- [ ] Node IP is the KubeSpan ULA IPv6 address
- [ ] Cilium agent runs on the node (DaemonSet pod healthy)

### Stage 5: Cilium + Full Connectivity

```bash
# Cilium agent healthy
kubectl get pods -n kube-system -l k8s-app=cilium -o wide | grep k8s-worker-test

# Deploy test pod
kubectl run test-ks --image=busybox --restart=Never \
  --overrides='{"spec":{"tolerations":[{"key":"node-role.kubernetes.io/roaming","operator":"Exists"}],"nodeSelector":{"node.kubernetes.io/role":"roaming"},"containers":[{"name":"test","image":"busybox","command":["sleep","3600"]}]}}'

# Cross-node pod connectivity
kubectl exec test-ks -- wget -qO- http://<service>.svc.cluster.local

# kubectl exec works (API server → kubelet via KubeSpan)
kubectl exec test-ks -- hostname

# DNS resolution
kubectl exec test-ks -- nslookup kubernetes.default.svc.cluster.local

# VXLAN MTU correct
kubectl exec -n kube-system <cilium-pod> -- ip link show cilium_vxlan
# Should show mtu 1370

# Large packet test (no fragmentation)
kubectl exec test-ks -- ping -c 3 -s 1300 <pod-ip-on-other-node>
```

Verify:

- [ ] Test pod schedules on laptop node
- [ ] Pod-to-pod networking works (VXLAN over KubeSpan)
- [ ] DNS resolution works inside pods
- [ ] `kubectl exec` works
- [ ] VXLAN MTU is 1370
- [ ] Large packets (1300 bytes) traverse without fragmentation

### Stage 6: Resilience

- [ ] kubespand restart: peers reconnect, kubelet stays running (or restarts via
      `Requires` dependency and recovers)
- [ ] Network change: KubeSpan endpoint cycling, kubelet node-ip (ULA) unchanged
- [ ] Sleep/wake: KubeSpan reconnects via discovery service

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
- **Mixed IPv4/IPv6 VTEP**: If Cilium can't handle mixed VTEP addresses (IPv4 Talos +
  IPv6 NixOS), fall back to advertising the real IP via kubespand `node_addresses` and
  using it as `--node-ip`.

## Open Questions

- **GPU sharing**: If the laptop has a GPU, it's available to both desktop and cluster
  workloads natively (no VFIO). Contention risk: desktop compositor vs CUDA jobs.
  May need cgroup isolation or manual coordination.
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
down, the NixOS worker would be effectively offline regardless. 2/3 CPs is sufficient for
API access.

## Appendix: KubeSpan Internals

KubeSpan is Talos-specific (no standalone client — confirmed by Sidero Labs in
[discussion #10032](https://github.com/siderolabs/talos/discussions/10032)).
kubespand reimplements the protocol for non-Talos Linux.

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

## Historical: Tailscale-based Architecture

The original design used Tailscale/Headscale as a second WireGuard mesh alongside KubeSpan.
This required:

- Tailscale DaemonSet on all cluster nodes
- Headscale dependency (runs in-cluster)
- Atlas advertising `10.2.0.0/16` as a Headscale subnet route
- Different connectivity model than Talos nodes

Replaced by kubespand + KubeSpan fabric (single mesh, uniform connectivity).
