# VPN/Overlay Network Alternatives Research

Research into alternatives to Tailscale/Headscale and Nebula for connecting
machines behind different NATs, with DNS support and public-IP relay nodes.

## Current Setup

- **Headscale** (active): Self-hosted Tailscale control server with MagicDNS and DERP relays
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
- **Verdict**: Strongest alternative to Headscale. Similar feature set, all three
  requirements met (NAT traversal, DNS, relay via public IPs).

### ZeroTier

- **Protocol**: Custom (not WireGuard), Layer 2 virtual Ethernet
- **License**: Client MPL-2.0, controller moved to commercial source-available in v1.16.0
- **NAT traversal**: Excellent
- **DNS**: Via companion tools (not built-in)
- **Relay**: Public-IP machines become "moons" (custom root/relay servers)
- **Self-hosting**: Possible but controller licensing changed
- **Web UI**: Via ztncui or similar third-party tools
- **Verdict**: Battle-tested, L2 semantics are unique. Licensing shift is a concern.

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

## Comparison Matrix

| Solution            | NAT Traversal        | DNS             | Public-IP Relay | Fully OSS | Complexity |
| ------------------- | -------------------- | --------------- | --------------- | --------- | ---------- |
| Headscale (current) | Excellent (DERP)     | MagicDNS        | DERP relay      | Yes       | Low        |
| NetBird             | Excellent (ICE/TURN) | Built-in        | TURN server     | Yes       | Low        |
| ZeroTier            | Excellent            | Companion tools | Moon servers    | Partially | Low        |
| Netmaker            | Good (TURN)          | Built-in        | Yes             | Open-core | High       |
| Innernet            | Basic (no relay)     | No              | No              | Yes       | Moderate   |
| Firezone            | Via gateway          | Yes             | Hub-spoke       | Open-core | Moderate   |
| OpenZiti            | Yes                  | Embedded        | Fabric routing  | Yes       | High       |

## Recommendation

**NetBird** is the strongest alternative if moving away from Headscale. It matches
the feature set (NAT traversal, DNS, relay) while being fully open source.

However, Headscale already satisfies all requirements well. The main reasons to
switch would be:

- Wanting to avoid Tailscale client dependency
- Needing features Headscale lacks (e.g., better ACL management UI)
- Preferring ICE/TURN over DERP for relay

## Sources

- <https://pinggy.io/blog/top_open_source_tailscale_alternatives/>
- <https://netbird.io/knowledge-hub/top-5-tailscale-alternatives>
- <https://netbird.io/compare>
- <https://dev.to/lightningdev123/open-source-alternatives-to-tailscale-in-2026-132p>
- <https://github.com/cedrickchee/awesome-wireguard>
