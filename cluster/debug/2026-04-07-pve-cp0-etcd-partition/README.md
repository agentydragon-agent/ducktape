# talos-pve-cp-0 etcd partition — 2026-04-07

## Summary

`talos-pve-cp-0` (10.42.0.10) has etcd SYN packets to `talos-vps-cp-0`
(10.42.0.1) **dropped before they reach the Nebula interface**. etcd can't
reach the leader, causing all API requests to time out (~14s each). The node
burns 272% CPU spinning on failed raft rounds.

## Timeline

- **2026-04-06 ~07:14 UTC**: Earliest Nebula logs show handshake timeouts to
  roaming nodes (10.42.0.30 = rugged, 10.42.0.31 = iguana) — expected, they're
  offline laptops.
- **2026-04-06 ~10:35 UTC**: Nebula handshakes to 10.42.0.1 (vps-cp-0) succeed
  normally.
- **2026-04-06 10:36:07 UTC**: Nebula tunnel to vps-cp-0 marked **"dead"**.
- **2026-04-06 10:37:50 UTC**: Tunnel re-established. Last successful kubelet
  heartbeat at this time.
- **2026-04-06 10:38:48 UTC**: Kubernetes marks node as `NotReady`
  ("Kubelet stopped posting node status"). Something broke during or right
  after the tunnel recovery.
- **2026-04-07 ~05:00 UTC**: Investigation begins. Node has been partitioned
  for ~18 hours.

## Root Cause Analysis

### What we know

1. **etcd on pve-cp-0 can't reach vps-cp-0 (10.42.0.1) on port 2380.**
   All etcd requests time out (~14s) waiting for "agreement among raft nodes
   before linearized reading." vps-cp-0 is the etcd leader.

2. **etcd to vps-cp-1 (10.42.0.2) works fine.** Multiple ESTABLISHED
   connections on port 2380, active data exchange confirmed via pcap.

3. **6 SYN_SENT sockets** from pve-cp-0 to 10.42.0.1:2380. Symmetric — vps-cp-0
   also has 7 SYN_SENT sockets to 10.42.0.10:2380.

4. **307 SYN_SENT entries in `/proc/net/nf_conntrack`** for 10.42.0.1:2380.
   All `[UNREPLIED]`, all different source ports. etcd has been churning through
   reconnect attempts for 18 hours.

5. **~~ICMP ping works~~** — CORRECTION: the ping/nc tests were run from the
   **Proxmox host** via `nsenter`, not from inside the VM. They tested host
   connectivity, not VM connectivity. Inside the VM, **all** connections to
   10.42.0.1 are SYN_SENT (including port 6443).

6. **Nebula logs show no errors** for 10.42.0.1 or 10.42.0.2 tunnels. Only
   handshake timeouts to offline roaming nodes.

7. **No conntrack table full** or netfilter drop messages in dmesg.

8. **No NMI/MCE/hardware errors** on Proxmox host or in VM.

9. **TCP retransmit stats**: 581k `ActiveOpens`, 135k `AttemptFails`,
   781k `RetransSegs` — massive failed connection churn.

### Critical finding: only 10.42.0.1 is broken

Connectivity from pve-cp-0 to all other Nebula peers works perfectly:

| Peer                  | State                        |
| --------------------- | ---------------------------- |
| 10.42.0.1 (vps-cp-0)  | **ALL SYN_SENT** (6 sockets) |
| 10.42.0.2 (vps-cp-1)  | All ESTABLISHED + TIME_WAIT  |
| 10.42.0.11 (vps-wk-0) | All ESTABLISHED              |
| 10.42.0.12 (vps-wk-1) | ESTABLISHED + TIME_WAIT      |
| 10.42.0.20 (wyrm2)    | ESTABLISHED + TIME_WAIT      |

This is a **single Nebula tunnel** issue — pve-cp-0 ↔ vps-cp-0 only.

### SYNs never reach the nebula1 interface

A pcap capture on `nebula1` interface for 8 seconds shows:

- **TCP 2380 to 10.42.0.2**: Active PUSH/ACK exchange — working
- **TCP 2380 to 10.42.0.1**: **Zero packets** — no SYNs at all

The kernel sees the SYNs (307 SYN_SENT entries in `/proc/net/nf_conntrack`)
but they never appear on the wire at `nebula1`.

### Correction: earlier `nc` tests were invalid

The `nc` and `ping` tests that appeared to show connectivity were run from the
**Proxmox host** via `nsenter -t <kvm-pid> -n` — this enters the host KVM
process's network namespace, **not** the VM's guest network. The host can reach
10.42.0.1 fine (it has its own Nebula instance). Inside the VM, everything to
10.42.0.1 is SYN_SENT.

### Hypothesis: broken Nebula tunnel for this specific peer

The Nebula tunnel between pve-cp-0 and vps-cp-0 went "dead" at 10:36:07 UTC
and "re-established" at 10:37:50 UTC. But the re-established tunnel is only
partially working — Nebula considers it up (no error logs for this peer), but
TCP packets from the VM to 10.42.0.1 are being silently dropped somewhere
in the Nebula/kernel path.

### Smoking gun: 574 million TX drops on `nebula1`

Interface counters from `/proc/net/dev` on pve-cp-0:

```text
nebula1 TX: pkts=2,811,346,483  drop=574,827,750 (20.4%)
```

The `nebula1` tun device is **dropping 20% of all outbound packets**. Drops
are still growing at **8,330/sec** (measured 2026-04-07T05:37:50Z–05:38:01Z:
575,190,723 → 575,274,023 = 83,300 drops in ~10s). This means the Nebula userspace process
can't drain the tun file descriptor fast enough — the kernel queues fill
up and packets are silently discarded.

For comparison, vps-cp-0's `nebula1` has only 5,776 TX drops total.

**Why this affects 10.42.0.1 specifically**: The massive volume of Cilium
VXLAN traffic (2.8 billion TX packets on `cilium_vxlan`, routed through
`nebula1`) is saturating the tunnel. The etcd SYNs to 10.42.0.1 are among
the 20% that get dropped. Connections to 10.42.0.2 work because those
SYNs happened to not be dropped (or were established before the drop rate
became critical), and once ESTABLISHED, TCP retransmission keeps them alive
through occasional drops.

**Root cause chain**:

1. Cilium VXLAN generates enormous traffic volume through `nebula1`
2. Nebula on pve-cp-0 can't keep up → tun device drops 20% of packets
3. etcd SYN packets to 10.42.0.1 are among the dropped packets
4. SYNs never reach Nebula → never get encrypted/sent → never arrive at
   vps-cp-0
5. etcd can't establish connection → raft consensus fails → node partitioned
6. 272% CPU from etcd/apiserver/kubelet retry loops makes Nebula even slower
   → positive feedback loop

**Why not all peers are affected**: Established TCP connections survive
occasional drops via retransmission. Only **new** connection attempts
(SYN packets) are fatally affected — a single dropped SYN means the entire
connection attempt fails and must restart. Once the node entered the
CPU-saturated state, the drop rate likely increased further, making it
impossible for any new SYN to 10.42.0.1 to succeed.

### CPU and traffic breakdown (measured 2026-04-07T05:37Z)

| Process        | CPU time (26h uptime) | Equivalent cores |
| -------------- | --------------------- | ---------------- |
| cilium-agent   | 90,915s               | ~1.0 core        |
| nebula         | 72,590s               | ~0.8 cores       |
| kube-apiserver | 4,912s                | ~0.05 cores      |
| etcd           | 4,114s                | ~0.04 cores      |
| kubelet        | 1,660s                | ~0.02 cores      |

Cilium + Nebula consume ~2 of 4 vCPUs.

**VXLAN TX rate**: 34,352 pkts/s on `cilium_vxlan` — absurd for a node with
only control plane pods. Total: 2.8 billion TX packets since boot. This is
likely Cilium replicating apiserver retry traffic across the VXLAN overlay.

**nebula1 TX drop rate**: 8,330/s (measured over 10s window).

Running pods: cilium-agent, cilium-envoy, kube-apiserver, kube-controller-manager,
kube-scheduler, promtail, nfd-worker. Nothing unusual.

### VXLAN packet capture analysis (30s capture, 2532 packets)

**99.8% of all VXLAN traffic** is a single flow:

```text
10.244.4.81:4242 → 10.244.1.207:4242  (2528/2532 packets)
```

- `10.244.4.81` = pve-cp-0 `cilium_host` IP
- `10.244.1.207` = a pod IP on vps-cp-0's CIDR
- Port 4242 = **Nebula's UDP port**

**This is Nebula traffic being VXLAN-encapsulated — a tunnel-in-tunnel loop.**

Nebula on pve-cp-0 sends UDP:4242 packets to peer on vps-cp-0. Cilium
sees the destination pod IP (`10.244.1.207`) as a remote pod and VXLAN-
encapsulates it. The VXLAN packet goes out through `nebula1` to reach
vps-cp-0. On arrival, it gets decapsulated, but the inner packet is
_another_ Nebula UDP packet, which may trigger further encapsulation or
retransmission — creating a **packet amplification loop**.

This explains the 48k pkts/s VXLAN TX on a node with no real workloads,
the 2.8 billion total TX packets, the Nebula tun overload, and the 574M
drops. The loop generates unbounded traffic that overwhelms the Nebula
userspace process.

### Cross-node comparison

| Node                      | Nebula CPU (26h) | nebula1 TX pkts | TX drops       |
| ------------------------- | ---------------- | --------------- | -------------- |
| **10.42.0.10 (pve-cp-0)** | **72,759s**      | **2,822M**      | **577M (20%)** |
| 10.42.0.1 (vps-cp-0)      | 37,919s          | 258M            | 5,776          |
| 10.42.0.2 (vps-cp-1)      | 35,211s          | 280M            | 4,709          |
| 10.42.0.11 (vps-wk-0)     | 18,201s          | 77M             | 0              |
| 10.42.0.12 (vps-wk-1)     | 25,023s          | 131M            | 0              |

pve-cp-0 sends **10x more packets** than any other node.

## Impact

- etcd on pve-cp-0 can't reach leader (vps-cp-0) → all reads time out
- kube-apiserver on pve-cp-0 is non-functional
- kubelet stops posting status → node goes NotReady
- 272% CPU wasted on retry loops
- Proxmox-pinned workloads can't schedule
- No data loss (cluster has 2/3 quorum from VPS CPs)

## Evidence Files

| File                     | Content                                                    |
| ------------------------ | ---------------------------------------------------------- |
| `pve-cp0-etcd.log`       | etcd logs — all requests timing out                        |
| `pve-cp0-nebula.log`     | Nebula logs — handshake timeouts, tunnel dead/alive        |
| `pve-cp0-netstat.log`    | SYN_SENT to 10.42.0.1:2380, ESTABLISHED to 10.42.0.2:2380  |
| `pve-cp0-dmesg.log`      | Kernel messages — no NMI/MCE/conntrack errors              |
| `pve-cp0-kubelet.log`    | kubelet timeout errors                                     |
| `pve-cp0-machined.log`   | Talos controller errors                                    |
| `pve-cp0-services.log`   | etcd health: Fail                                          |
| `pve-cp0-addresses.log`  | Network addresses — 10.2.1.1/16 eth0, 10.42.0.10/16 nebula |
| `pve-cp0-routes.log`     | Routing table                                              |
| `pve-cp0-processes.log`  | Process list                                               |
| `pve-cp0-memory.log`     | Memory usage                                               |
| `pve-cp0-mounts.log`     | Mount points                                               |
| `pve-cp0-containerd.log` | containerd logs                                            |
| `pve-cp0-apid.log`       | Talos API logs                                             |
| `pve-cp0-trustd.log`     | Talos trust daemon logs                                    |
| `vps-cp0-etcd.log`       | Leader etcd — peer unreachable errors                      |
| `vps-cp0-netstat.log`    | SYN_SENT to 10.42.0.10:2380 (symmetric)                    |
| `vps-cp0-nebula.log`     | Nebula logs from vps-cp-0                                  |
| `vps-cp0-dmesg.log`      | vps-cp-0 kernel messages                                   |
| `vps-cp0-services.log`   | vps-cp-0 service status                                    |
| `vps-cp1-etcd.log`       | Third etcd member logs                                     |
| `vps-cp1-netstat.log`    | Third member connections                                   |
| `etcd-status-all.log`    | etcd cluster status — vps-cp-0 is leader                   |
| `k8s-events.log`         | All cluster events                                         |
| `k8s-node-describe.log`  | kubectl describe node — condition timestamps               |
| `atlas-dmesg-tail.log`   | Proxmox host kernel — clean                                |
| `atlas-top.log`          | Proxmox host load                                          |
| `pve-vm-status.log`      | qm status --verbose output                                 |
| `pve-vm-proc-status.log` | /proc/4059/status for the VM process                       |

### ~~Missing default route~~ — DISPROVED

Initial investigation using `talosctl get routestatuses` suggested no default route.
However, `/proc/net/route` shows the kernel FIB **does** have `0.0.0.0/0 via 10.2.0.1
dev eth0 metric 1024`. The `talosctl get routestatuses` output was misleading — it
showed the route as `inet4/10.2.0.1//1024` (gateway-only entry) rather than with an
explicit `0.0.0.0/0` destination.

Confirmed working:

- ESTABLISHED TCP connections to VPS public IPs (5.78.x.x:6443) from 10.2.1.1
- Active UDP:4242 conntrack entries to all 3 lighthouses
- The VM has full internet connectivity via the VLAN gateway

**The default route is NOT the problem.** The VXLAN amplification loop has a
different cause.

### Revised understanding

The VXLAN traffic `10.244.4.81:4242 → 10.244.1.207:4242` is:

- Source: pve-cp-0's `cilium_host` IP, port 4242 (Nebula)
- Dest: `10.244.1.207` — a **stale pod IP** not assigned to any current pod

This IP may have been the **ActivityWatch pod** which ran a Nebula sidecar
container (UDP:4242) and was recently suspended. If the pod was deleted but
Cilium's endpoint/VXLAN FDB wasn't cleaned up, traffic to that IP would
loop through VXLAN indefinitely.

### ACTUAL root cause: Nebula on VPS nodes binds to pod CIDR IPs

Nebula logs on pve-cp-0 show handshakes from vps-cp-0 arriving **from
`10.244.1.207:4242`** — a Cilium pod CIDR IP, not the public IP or host IP:

```json
"from":{"direct":"10.244.1.207:4242"} ... "vpnAddrs":["10.42.0.1"]
```

This is also visible for other VPS nodes:

- vps-worker-1: `10.244.0.28:4242`
- vps-worker-0: `10.244.3.2:4242`

**Nebula on the Talos VPS nodes is binding to their `cilium_host` or pod CIDR
IP instead of their public IP.** When these nodes send Nebula handshakes,
they use pod IPs as source. The receiving Nebula (pve-cp-0) learns
`10.244.1.207:4242` as vps-cp-0's UDP endpoint.

When pve-cp-0's Nebula sends return traffic to `10.244.1.207:4242`:

1. Kernel routes `10.244.1.0/24` via `cilium_host` (Cilium VXLAN)
2. Cilium VXLAN-encapsulates the packet
3. VXLAN outer packet goes through `nebula1` to reach vps-cp-0
4. On vps-cp-0, VXLAN decapsulates → inner packet is UDP:4242 to a pod IP
5. This may bounce back or create further encapsulation → **amplification loop**

**Why it only affects pve-cp-0**: VPS-to-VPS VXLAN works directly over the
Hetzner L2 network without Nebula. Only the Proxmox node needs to cross
the Nebula tunnel for VXLAN, creating the tunnel-in-tunnel scenario.

**Why `10.244.1.207` is not assigned to any current pod**: This was likely
the `cilium_host` IP or a node-local IP that Nebula auto-detected on
vps-cp-0 at some point. The IP may have changed after a Cilium restart,
but pve-cp-0's Nebula still has it cached as the peer's UDP endpoint.

**Fix**: `nebula.tf` line 56 sets `listen = { host = "0.0.0.0", port = 4242 }`
for all nodes. `0.0.0.0` means bind to all interfaces — the kernel picks the
source IP from the routing table, which may be a `cilium_host` pod CIDR IP
when the route to the peer goes through Cilium routes. The peer then caches
this pod CIDR IP as the sender's UDP endpoint.

Change `listen.host` per node:

- VPS nodes: bind to public IP (e.g., `hcloud_server.vps["vps0"].ipv4_address`)
- Proxmox node: bind to VLAN IP (`10.2.1.1`)

This ensures Nebula always advertises the correct source IP to peers.

## Resolution

**Fixed** by adding `lighthouse.local_allow_list` to all Nebula configs,
blocking `cilium.*` and `lxc.*` interfaces from being advertised:

```terraform
# nebula.tf
nebula_local_allow_list = {
  interfaces = {
    "cilium.*" = false
    "lxc.*"    = false
  }
}
```

Applied via `tofu apply -target=talos_machine_configuration_apply.proxmox["pve_cp0"]`.
Talos restarted the Nebula extension automatically (no reboot needed).

**Result** (immediate):

- nebula1 TX drops: 577M → **0**
- nebula1 TX pkts/s: 48k → **normal**
- Nebula CPU: 72,590s → **13s**
- etcd: Fail → **OK**
- Node: NotReady → **Ready**

Same fix applied to `nix/nixos/modules/nebula-mesh.nix` for NixOS workers.

## Prevention

- [ ] Alert on `node_network_transmit_drop_total{device="nebula1"}` rate > 10/s
- [ ] Alert on etcd health check failures
- [ ] Fix monitoring stack (Mimir ring unhealthy, kube-prometheus-stack stalled)
      so metrics are actually collected
