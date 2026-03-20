# VPN/Overlay Network Alternatives Research

Research into alternatives to Tailscale/Headscale and Nebula for connecting
machines behind different NATs, with DNS support and public-IP relay nodes.

Primary use case: **cluster fabric** (inter-node connectivity for Kubernetes),
not general-purpose device mesh.

## Current Setup

- **Headscale** (active): Self-hosted Tailscale control server with MagicDNS and DERP relays
- **KubeSpan** (active): Talos-native WireGuard mesh for cluster inter-node traffic.
  No relay fallback — plain WireGuard with UDP hole-punching via discovery service.
  If direct UDP connectivity fails, the connection fails entirely.
- **Nebula** (prepared, not deployed): PKI ready in Terraform, planned as KubeSpan successor

## Alternatives Evaluated

### NetBird

- **Protocol**: WireGuard + ICE/TURN (WebRTC-style negotiation)
- **License**: BSD-3, fully open source
- **NAT traversal**: Excellent — uses STUN for P2P, falls back to TURN relay
- **DNS**: Built-in DNS management
- **Relay**: Public-IP machines run TURN/signal servers
- **Self-hosting**: ~5 minutes setup, well-documented
- **Web UI**: Yes
- **Verdict**: Strongest alternative to Headscale for device mesh. Similar feature
  set, all three requirements met (NAT traversal, DNS, relay via public IPs).
  Less suited for cluster fabric due to ICE negotiation overhead and operational
  complexity (3 server components).

### ZeroTier

- **Protocol**: Custom (not WireGuard), Layer 2 virtual Ethernet
- **License**: Client MPL-2.0, controller moved to commercial source-available in v1.16.0
- **NAT traversal**: Excellent
- **DNS**: Via companion tools (not built-in)
- **Relay**: Public-IP machines become "moons" (custom root/relay servers)
- **Self-hosting**: Possible but controller licensing changed
- **Web UI**: Via ztncui or similar third-party tools
- **Verdict**: Battle-tested, L2 semantics are unique. Licensing shift is a concern.
  Weakest fabric option due to userspace-only custom protocol and slow peer discovery
  (10-30s through roots).

### Netmaker

- **Protocol**: WireGuard (kernel or userspace)
- **License**: Open-core
- **NAT traversal**: Good (TURN), historically had reliability issues
- **DNS**: Built-in
- **Relay**: Yes, via designated relay nodes
- **Self-hosting**: Yes, but complex and resource-heavy
- **Web UI**: Yes
- **Verdict**: Feature-rich but operationally heavy. TURN relay had reliability
  issues in academic testing (v0.20.0).

### Innernet

- **Protocol**: WireGuard, Rust implementation
- **License**: Fully open source (MIT)
- **NAT traversal**: Basic — no relay fallback, UDP only
- **DNS**: No built-in DNS
- **Relay**: No (lighthouse for coordination only, not relay)
- **Self-hosting**: Yes, minimal
- **Web UI**: No (CLI only)
- **Verdict**: Clean and minimal but lacks relay and DNS. Not suitable if machines
  are behind restrictive NATs that block UDP.

### Firezone

- **Protocol**: WireGuard
- **License**: Elastic (open-core, considered proprietary by some)
- **NAT traversal**: Via gateway nodes
- **DNS**: Yes
- **Relay**: Hub-spoke via gateways
- **Self-hosting**: Yes
- **Web UI**: Yes, polished
- **Verdict**: Good zero-trust platform but hub-spoke topology (not full mesh)
  and licensing concerns.

### OpenZiti

- **Protocol**: Custom zero-trust overlay
- **License**: Apache 2.0
- **NAT traversal**: Yes (no open inbound ports needed)
- **DNS**: Embedded DNS
- **Relay**: Built-in fabric routing
- **Self-hosting**: Yes, but complex
- **Verdict**: Most ambitious zero-trust architecture. High complexity, best for
  application-level embedding rather than general-purpose mesh VPN.

## General Comparison Matrix

| Solution            | NAT Traversal        | DNS             | Public-IP Relay | Fully OSS | Complexity |
| ------------------- | -------------------- | --------------- | --------------- | --------- | ---------- |
| Headscale (current) | Excellent (DERP)     | MagicDNS        | DERP relay      | Yes       | Low        |
| NetBird             | Excellent (ICE/TURN) | Built-in        | TURN server     | Yes       | Low        |
| ZeroTier            | Excellent            | Companion tools | Moon servers    | Partially | Low        |
| Netmaker            | Good (TURN)          | Built-in        | Yes             | Open-core | High       |
| Innernet            | Basic (no relay)     | No              | No              | Yes       | Moderate   |
| Firezone            | Via gateway          | Yes             | Hub-spoke       | Open-core | Moderate   |
| OpenZiti            | Yes                  | Embedded        | Fabric routing  | Yes       | High       |

## Talos Linux Extensions

Official Talos extensions from [siderolabs/extensions](https://github.com/siderolabs/extensions):

| Solution     | Talos Extension | Image                          |
| ------------ | --------------- | ------------------------------ |
| Tailscale    | Yes             | `ghcr.io/siderolabs/tailscale` |
| Nebula       | Yes             | `ghcr.io/siderolabs/nebula`    |
| **NetBird**  | Yes             | `ghcr.io/siderolabs/netbird`   |
| **ZeroTier** | Yes             | `ghcr.io/siderolabs/zerotier`  |
| Netmaker     | No              | —                              |
| Innernet     | No              | —                              |
| Firezone     | No              | —                              |

Extensions run as system services on Talos nodes, packaged under
`/usr/local/lib/containers/{name}/`. This is relevant for the Talos cluster
where KubeSpan currently provides the inter-node mesh.

## Cluster Fabric Considerations

When evaluating mesh networks for cluster inter-node fabric (as opposed to
general device mesh), different criteria dominate.

### Kernel WireGuard vs Userspace

Kernel WireGuard handles encryption in the kernel data path with no context
switches per packet. Userspace implementations add CPU overhead and latency.

| Solution           | Kernel WireGuard | Notes                                   |
| ------------------ | ---------------- | --------------------------------------- |
| KubeSpan (current) | Yes              | Talos-native                            |
| Nebula             | No               | Custom Noise protocol, userspace        |
| NetBird            | Yes              | Prefers kernel, falls back to userspace |
| ZeroTier           | No               | Custom protocol, entirely userspace     |
| Netmaker           | Yes              | Prefers kernel, falls back to userspace |
| Innernet           | Yes              | Kernel WireGuard                        |
| Raw WireGuard      | Yes              | Manual config, no NAT traversal         |

### TCP Relay Fallback and TCP-in-TCP Meltdown

When NAT hole-punching fails, some solutions fall back to relaying over TCP
(DERP, TURN-over-TCP). For cluster fabric this is catastrophic — TCP-in-TCP
causes retransmission amplification. etcd, API server, and pod traffic all use
TCP; wrapping in another TCP layer means a single packet loss triggers
retransmissions at both layers.

| Solution            | Relay protocol               | TCP-in-TCP risk                          |
| ------------------- | ---------------------------- | ---------------------------------------- |
| KubeSpan            | None (no relay)              | No — but connection fails if UDP blocked |
| Tailscale/Headscale | DERP (TCP/HTTPS)             | Yes, when hole-punching fails            |
| Nebula              | UDP only (no relay fallback) | No — but connection fails if UDP blocked |
| NetBird             | TURN (UDP preferred, TCP fb) | Yes, on TCP fallback                     |
| ZeroTier            | UDP relay via roots/moons    | Low — stays UDP                          |
| Netmaker            | TURN (UDP preferred, TCP fb) | Yes, on TCP fallback                     |
| Innernet            | No relay                     | No — but connection fails if no direct   |

### Convergence Time and Connection Stability

etcd has tight heartbeat/election timeouts (default 500ms heartbeat, 5s
election). If the mesh takes seconds to reconverge after a path change,
leader elections and potential split-brain result.

- **KubeSpan**: WireGuard handshake ~1 RTT, peer state checked every ~15s
- **Nebula**: Lighthouse-coordinated, handshake per connection, ~1-2 RTT
- **NetBird**: ICE negotiation involves STUN probing — can take seconds for
  initial setup. Once established, WireGuard is fast
- **ZeroTier**: Peer discovery can take 10-30s through roots

### Encapsulation Overhead (MTU Budget)

Current setup: 1370 MTU (1500 - 50 VXLAN - 80 WireGuard). Different solutions
have similar overhead:

| Solution                      | Overhead (bytes) | Pod MTU with VXLAN |
| ----------------------------- | ---------------- | ------------------ |
| WireGuard (KubeSpan, NetBird) | ~80              | 1370               |
| Nebula (Noise + UDP)          | ~60-80           | ~1370              |
| ZeroTier (custom framing)     | ~80-100          | ~1350              |

Not a major differentiator.

### Failure Mode Complexity

For infrastructure fabric, simpler = better. Each additional component is
another thing that can break and take the cluster down. However, distinguish
between what runs **on each node** (the agent/client) vs what runs as
**infrastructure** (can be a pod, a separate VM, or even a SaaS).

| Solution | Node-side       | Infrastructure components       | Failure characteristics                              |
| -------- | --------------- | ------------------------------- | ---------------------------------------------------- |
| KubeSpan | Built-in        | Discovery service (`talos.dev`) | External dependency on discovery                     |
| Nebula   | Talos extension | Lighthouse(s) only              | Simple — lighthouse down = no new conns, existing up |
| NetBird  | Talos extension | Mgmt + signal + relay (or SaaS) | More components, but can run as k8s pods or SaaS     |
| ZeroTier | Talos extension | Controller + root servers       | Controller down = no config changes, existing up     |
| Netmaker | No extension    | Server + TURN + DNS + UI        | Complex, many components                             |

**NetBird nuance**: The 3 server components (management, signal, relay) don't
run on the nodes — only the lightweight client agent does. The server
components can run as pods in the cluster, on a separate VM, or even use
NetBird's hosted SaaS (`api.netbird.io`). Since v0.29, management and signal
share ports via HTTP/2, reducing to effectively 2 services + STUN. The default
single-server deployment bundles all components into one container behind
Traefik. Clients tolerate management server outages — existing P2P and relay
connections survive.

### Pod/Service CIDR Routing

KubeSpan is special — it's integrated with Talos and automatically routes pod
CIDRs across nodes. The other solutions just provide point-to-point tunnels;
Cilium VXLAN handles pod routing on top. For Nebula/NetBird/ZeroTier as fabric,
Cilium VXLAN still runs over the tunnel — the mesh just replaces the encrypted
transport layer.

## Cluster Fabric Comparison

| Criterion              | KubeSpan       | Nebula         | NetBird        | ZeroTier       |
| ---------------------- | -------------- | -------------- | -------------- | -------------- |
| Kernel crypto          | Yes            | No             | Yes            | No             |
| NAT traversal          | Limited        | Weaker         | Best           | Good           |
| TCP meltdown risk      | No (no relay)  | No             | Yes (TURN-TCP) | Low            |
| Node agent complexity  | Built-in       | Simple         | Simple         | Simple         |
| Infra components       | 0 (built-in)   | 1 (lighthouse) | 1-3 (or SaaS)  | 1 (controller) |
| Convergence speed      | Fast           | Fast           | Slower (ICE)   | Slow           |
| Maturity for fabric    | Designed for   | Slack-scale    | Device-focused | Device-focused |
| Talos extension        | Built-in       | Yes            | Yes            | Yes            |
| Pod CIDR routing       | Automatic      | Manual/Cilium  | Manual/Cilium  | Manual/Cilium  |
| Survives ctrl plane dn | No (no relay)  | Yes            | Yes            | Yes            |
| VPS can host infra     | N/A (built-in) | Yes (natural)  | Hard           | Hard           |

## Bootstrap Problem: VPS Talos Nodes as Mesh Infrastructure

If the VPS Talos nodes themselves must host the mesh infrastructure (because
the mesh IS the inter-node fabric), there's a chicken-and-egg constraint: the
mesh infra must be reachable _before_ the mesh is up, so it must run at the
system level (Talos extension or host service), not as a Kubernetes pod.

### How each option handles this

**Nebula — works naturally.** The lighthouse IS just a regular Nebula node with
`am_lighthouse: true` in its config. VPS nodes run the same Nebula binary as
every other node, just with one extra config flag. No separate server software,
no separate container, no separate process. The Talos extension handles
everything. This is the ideal architecture for self-hosted fabric on Talos.

**NetBird — bootstrap problem.** The management/signal/relay server is a
separate binary from the client agent. It needs SQLite/Postgres, Traefik for
TLS, and serves a web UI. Options:

- **As a k8s pod**: Chicken-and-egg — cluster needs mesh, mesh needs management
- **As a Talos extension**: Only the client agent is packaged, not the server
- **On a non-Talos VPS**: Works but defeats the goal
- **Via SaaS** (`api.netbird.io`): Avoids the problem but adds external dependency

NetBird's architecture fundamentally separates client from server. The server
can't easily run on Talos nodes as system-level infrastructure.

**ZeroTier — similar problem.** The controller is separate software. Moon nodes
(relay) work, but the controller still needs to run somewhere accessible.
Controller licensing is also commercially restricted.

**KubeSpan — already does this.** Discovery is external (`talos.dev`), but the
WireGuard mesh between nodes is self-contained at the system level. Limited
NAT traversal though (no relay fallback).

### Summary

For "VPS Talos nodes host the mesh infra", the only option that works cleanly
is **Nebula** — the lighthouse is architecturally identical to any other node.
NetBird and ZeroTier require separate server software that doesn't fit the
Talos extension model.

## Talos Extension Configuration Examples

### NetBird on Talos

Node-side config is minimal — just a setup key and management URL:

```yaml
# netbird-config.yaml — apply with: talosctl patch mc -p @netbird-config.yaml
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: netbird
environment:
  - NB_SETUP_KEY=<peer setup key>
  - NB_MANAGEMENT_URL=https://netbird.allegedly.works:443
  - NB_ADMIN_URL=https://netbird.allegedly.works:443
```

The server side (management + signal + relay) runs separately — as a pod in the
cluster, on a VM, or via NetBird's SaaS. Default single-server deployment
bundles everything behind Traefik on ports 80/443 (TCP) + 3478 (UDP/STUN).

Since v0.29, management and signal share ports via HTTP/2. Minimal
self-hosted deployment is one container + a domain with TLS.

### Nebula on Talos

Requires PKI certificates (already prepared in Terraform).

**VPS node (lighthouse)** — same extension, `am_lighthouse: true`:

```yaml
# nebula-lighthouse.yaml — VPS node with public IP
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: nebula
configFiles:
  - content: |
      pki:
        ca: /usr/local/etc/nebula/ca.crt
        cert: /usr/local/etc/nebula/node.crt
        key: /usr/local/etc/nebula/node.key
      lighthouse:
        am_lighthouse: true
      listen:
        host: 0.0.0.0
        port: 4242
      tun:
        dev: nebula1
      firewall:
        outbound:
          - port: any
            proto: any
            host: any
        inbound:
          - port: any
            proto: any
            host: any
    mountPath: /usr/local/etc/nebula/config.yml
  - content: <ca-certificate-pem>
    mountPath: /usr/local/etc/nebula/ca.crt
  - content: <node-certificate-pem>
    mountPath: /usr/local/etc/nebula/node.crt
  - content: <node-private-key-pem>
    mountPath: /usr/local/etc/nebula/node.key
```

**Non-VPS node (behind NAT)** — points to lighthouses:

```yaml
# nebula-node.yaml — node behind NAT
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: nebula
configFiles:
  - content: |
      pki:
        ca: /usr/local/etc/nebula/ca.crt
        cert: /usr/local/etc/nebula/node.crt
        key: /usr/local/etc/nebula/node.key
      lighthouse:
        hosts:
          - "<vps1-nebula-ip>"
          - "<vps2-nebula-ip>"
      static_host_map:
        "<vps1-nebula-ip>":
          - "<vps1-public-ip>:4242"
        "<vps2-nebula-ip>":
          - "<vps2-public-ip>:4242"
      listen:
        host: 0.0.0.0
        port: 4242
      tun:
        dev: nebula1
      firewall:
        outbound:
          - port: any
            proto: any
            host: any
        inbound:
          - port: any
            proto: any
            host: any
    mountPath: /usr/local/etc/nebula/config.yml
  - content: <ca-certificate-pem>
    mountPath: /usr/local/etc/nebula/ca.crt
  - content: <node-certificate-pem>
    mountPath: /usr/local/etc/nebula/node.crt
  - content: <node-private-key-pem>
    mountPath: /usr/local/etc/nebula/node.key
```

Key point: the lighthouse is the same binary with one extra flag. Both VPS and
NAT nodes use the same Talos extension. PKI is more verbose than NetBird's
setup key, but Terraform already has the CA and cert generation prepared.

## Recommendation

### For cluster fabric (VPS-hosted infra)

**Nebula** is the only option that cleanly supports VPS Talos nodes hosting the
mesh infrastructure:

- Lighthouse = same binary with one flag — no bootstrap problem
- No TCP meltdown risk (UDP only, no relay fallback)
- Designed for infrastructure (built at Slack for exactly this)
- Certificate-based trust model suits infrastructure well
- PKI already prepared in Terraform
- Zero external dependencies once running
- 2 VPS lighthouses provide redundancy

Downsides to accept:

- Userspace crypto (no kernel WireGuard) — more CPU per packet
- Weaker NAT traversal (UDP hole-punching only, no relay). Acceptable when at
  least one side has a public IP (true for VPS↔home and VPS↔VPS connections).
  Problem only if both sides are behind NAT with no public IP.
- More verbose Talos config (PKI files vs one setup key)
- Experimental DNS support (lighthouse-only, no forwarding)

NetBird is not viable for this use case due to the bootstrap problem — the
management server can't run as a Talos extension.

### For device mesh (laptops, phones)

Keep **Headscale** or evaluate **NetBird**:

- Best NAT traversal (ICE/TURN)
- Built-in DNS with forwarding
- Web UI for management
- Management server can run as a k8s pod (no bootstrap problem for device
  mesh — the cluster is already up when devices connect)

### Combined architecture

- **Nebula** for cluster fabric (Talos extension on all nodes, VPS as lighthouses)
- **Headscale** (or NetBird) for device mesh (k8s pod, separate concern)

This separates infrastructure fabric (must bootstrap before k8s) from device
mesh (runs on top of k8s). Each tool handles what it's designed for.

## Sources

- <https://pinggy.io/blog/top_open_source_tailscale_alternatives/>
- <https://netbird.io/knowledge-hub/top-5-tailscale-alternatives>
- <https://netbird.io/compare>
- <https://dev.to/lightningdev123/open-source-alternatives-to-tailscale-in-2026-132p>
- <https://github.com/cedrickchee/awesome-wireguard>
- <https://github.com/siderolabs/extensions>
- <https://deepwiki.com/siderolabs/extensions/3.4-networking-extensions>
- <https://docs.netbird.io/about-netbird/how-netbird-works>
- <https://docs.netbird.io/selfhosted/selfhosted-guide>
- <https://docs.netbird.io/selfhosted/maintenance/scaling/scaling-your-self-hosted-deployment>
- <https://github.com/siderolabs/talos/discussions/8338>
