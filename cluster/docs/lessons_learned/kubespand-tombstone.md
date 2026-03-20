# Tombstone: kubespand (KubeSpan for Non-Talos Linux)

**Built**: 2025-10 to 2025-12
**Decommissioned**: 2026-03
**Replacement**: Nebula mesh (lighthouses + relays, cert-based PKI)

## What It Was

kubespand (~15k LOC Go, ~8k LOC QEMU integration tests) reimplemented Talos's KubeSpan
mesh for non-Talos Linux workers. Built on the COSI (Controller Runtime for Sidero) framework
— the same resource/controller model Talos uses internally.

Components:

- **WireGuard mesh controller**: managed kernel WireGuard interfaces, peer configuration,
  routing rules, and `rp_filter` sysctl tuning
- **Discovery service client**: participated in Talos cluster discovery to learn peer
  endpoints (same protocol as Talos nodes)
- **KubePrism proxy**: `localhost:7445` → control plane API load balancer, so workers
  could use a stable local endpoint for kubelet bootstrap
- **apid mTLS proxy**: mutual TLS proxy for the Talos API, enabling `talosctl` to reach
  non-Talos workers through the same management plane
- **QEMU integration tests**: full network topology simulation (flat subnet, cross-subnet,
  double NAT) using QEMU VMs with kernel modules extracted from NixOS

## Why It Was Built

Talos's KubeSpan only exists inside Talos. No standalone client is available for joining
non-Talos Linux machines to a KubeSpan mesh. Sidero Labs' position
([discussion #10032](https://github.com/siderolabs/talos/discussions/10032)) is that
KubeSpan is tightly coupled to the Talos controller runtime.

The goal was to join NixOS GPU workers (wyrm2) and roaming laptops (rugged) to the
cluster mesh without running Talos on those machines.

## What Killed It

**KubeSpan has no relay or hole-punching mechanism.** It requires at least one side of
every peer pair to have a reachable UDP port. This is architecturally unfixable without
changes to KubeSpan itself.

Specific failure modes:

- **Double NAT**: Two nodes behind separate NATs (e.g., home network + carrier-grade NAT,
  or two different home networks) cannot establish WireGuard tunnels. Neither side can
  reach the other's UDP port. The endpoint cycling mechanism averages ~240 seconds per
  attempt and still fails.
- **Roaming laptops**: A laptop on coffee shop WiFi behind NAT cannot connect to a home
  server also behind NAT. This was the primary use case for rugged.
- **No relay architecture**: Unlike Nebula (lighthouses + relays) or Tailscale (DERP servers),
  KubeSpan has no relay nodes that can bridge traffic between unreachable peers.

The QEMU double-NAT test (`qemu_tests/doublenat/`) confirmed this limitation conclusively.

## What Worked Well

- **COSI framework**: Clean resource/controller separation. Controllers watch typed
  resources and reconcile state, exactly like Talos internals. Good fit for system-level
  networking.
- **Discovery service**: Successfully participated in Talos cluster discovery alongside
  real Talos nodes.
- **QEMU tests**: Reliable, reproducible network topology testing. Boot real Linux VMs
  with extracted kernel modules, set up iptables NAT, verify WireGuard tunnels.
- **KubePrism**: Simple, effective local API proxy. Workers could bootstrap kubelet against
  `localhost:7445` without knowing control plane IPs upfront.

## Key Technical Findings

- **`rp_filter` routing**: WireGuard decapsulated packets arrive on `kubespan0` with
  source IPs whose reverse path goes via `eth0`. `rp_filter=1` (strict) drops them.
  Must set `rp_filter=0` (or `2` for loose). Same issue affects Nebula.
- **MagicDNS SRV dropping**: Tailscale's MagicDNS silently drops SRV queries matching
  certain patterns. gRPC-Go's `dns:///` resolver does SRV lookups by default; use
  `passthrough:///` scheme to bypass. (See `debug/kubespand-grpc-dns-magicdns.md`,
  preserved in repo debug notes.)
- **Linux kernel boundary**: Talos's controller runtime (`machined`) manages WireGuard
  via netlink from userspace. Embedding Talos controllers in a standalone binary was
  feasible but hit the boundary at kernel module management — Talos assumes it controls
  the entire OS.

## Replacement: Nebula

Nebula (MIT, originally Slack) solves the relay problem architecturally:

- **Lighthouses**: Well-known nodes with public IPs that peers register with
- **Relays**: Lighthouse nodes can relay traffic for peers that can't reach each other
- **Punchy**: Aggressive NAT hole-punching with configurable `respond: true`
- **Certificate PKI**: CA issues per-node certs with embedded Nebula IPs and group membership

The cluster runs Nebula on all nodes: Talos nodes via the `siderolabs/nebula` system
extension, NixOS workers via a custom `nebula-mesh.nix` module with cloud-init credential
injection.

Migration was straightforward — Nebula was deployed alongside KubeSpan on the Talos nodes
first, then KubeSpan was disabled and kubespand was removed from the NixOS worker stack.
