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

For infrastructure fabric, simpler = better. Each additional component (STUN
server, TURN server, signal server, management API) is another thing that can
break and take the cluster down.

| Solution | Components needed                  | Failure characteristics                              |
| -------- | ---------------------------------- | ---------------------------------------------------- |
| KubeSpan | Discovery service (`talos.dev`)    | External dependency on discovery                     |
| Nebula   | Lighthouse(s) only                 | Simple — lighthouse down = no new conns, existing up |
| NetBird  | Mgmt server + signal server + TURN | Most moving parts                                    |
| ZeroTier | Controller + root servers          | Controller down = no config changes, existing up     |
| Netmaker | Server + TURN + DNS + UI           | Complex, many components                             |

### Pod/Service CIDR Routing

KubeSpan is special — it's integrated with Talos and automatically routes pod
CIDRs across nodes. The other solutions just provide point-to-point tunnels;
Cilium VXLAN handles pod routing on top. For Nebula/NetBird/ZeroTier as fabric,
Cilium VXLAN still runs over the tunnel — the mesh just replaces the encrypted
transport layer.

## Cluster Fabric Comparison

| Criterion              | KubeSpan      | Nebula         | NetBird        | ZeroTier       |
| ---------------------- | ------------- | -------------- | -------------- | -------------- |
| Kernel crypto          | Yes           | No             | Yes            | No             |
| NAT traversal          | Limited       | Weaker         | Best           | Good           |
| TCP meltdown risk      | No (no relay) | No             | Yes (TURN-TCP) | Low            |
| Operational simplicity | Best          | Simple         | Complex        | Moderate       |
| Convergence speed      | Fast          | Fast           | Slower (ICE)   | Slow           |
| Maturity for fabric    | Designed for  | Slack-scale    | Device-focused | Device-focused |
| Talos extension        | Built-in      | Yes            | Yes            | Yes            |
| Pod CIDR routing       | Automatic     | Manual/Cilium  | Manual/Cilium  | Manual/Cilium  |
| Server components      | 0 (built-in)  | 1 (lighthouse) | 3              | 1 (controller) |
| Failure blast radius   | Low           | Low            | High           | Moderate       |

## Recommendation

### For cluster fabric

**Nebula** is the strongest fabric candidate despite weaker NAT traversal:

- Simple (lighthouse-only architecture)
- No TCP meltdown risk (UDP only)
- Designed for infrastructure (built at Slack for exactly this)
- Public-IP machines as lighthouses solve NAT (at least one side always public)
- Certificate-based trust model suits infrastructure well
- PKI already prepared in Terraform
- Talos extension available

Main downside: userspace crypto (no kernel WireGuard), but Nebula's Noise
protocol is fast enough for most cluster workloads.

### For device mesh (laptops, phones)

**NetBird** is the strongest device mesh candidate:

- Best NAT traversal (ICE/TURN)
- Built-in DNS
- Fully open source
- Web UI for management
- Talos extension available

ICE negotiation overhead and 3-component server architecture make it less
suited for infrastructure fabric, but those trade-offs are fine for device mesh
where connection setup time is less critical.

### Split architecture option

Run **Nebula** for cluster fabric and **NetBird** (or keep Headscale) for device
mesh. Different tools for different requirements.

## Sources

- <https://pinggy.io/blog/top_open_source_tailscale_alternatives/>
- <https://netbird.io/knowledge-hub/top-5-tailscale-alternatives>
- <https://netbird.io/compare>
- <https://dev.to/lightningdev123/open-source-alternatives-to-tailscale-in-2026-132p>
- <https://github.com/cedrickchee/awesome-wireguard>
- <https://github.com/siderolabs/extensions>
- <https://deepwiki.com/siderolabs/extensions/3.4-networking-extensions>
