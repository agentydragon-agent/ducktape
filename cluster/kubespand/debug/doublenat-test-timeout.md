# Double-NAT QEMU Test Timeout Analysis

**Date**: 2026-03-18 (initial), 2026-03-19 (updated with live log data)
**Status**: Root cause identified — endpoint cycling alignment problem

## Symptom

Both `doublenat_kubespand_test` and `doublenat_talos_test` fail: the NAT-to-NAT peer
connection never comes up. Hub-spoke connections (VPS↔NAT1, VPS↔NAT2) establish in
~20s, but NAT1↔NAT2 stays `unknown` indefinitely.

The flat topology test (same mesh convergence criteria) passes in ~106s.

## Network Topology

```text
[NAT1 192.168.60.2] --[LAN-A 192.168.60.0/24]-- [Router-A 192.168.50.1] --+
                                                                             |
                                                                        [Internet 192.168.50.0/24]
                                                                             |
[NAT2 192.168.70.2] --[LAN-B 192.168.70.0/24]-- [Router-B 192.168.50.3] --+
                                                                             |
                                                                        [VPS 192.168.50.2]
                                                                      [Discovery 192.168.50.254]
```

6 QEMU VMs total: 3 infrastructure (discovery, router-a, router-b) + 1 VPS (Talos CP)
\+ 2 workers (Talos or kubespand depending on variant). All under TCG software
emulation (no KVM), `-machine accel=tcg`, 4 host CPUs (`cpu:4` tag).

Routers use nftables masquerade with `Persistent: true` (endpoint-independent mapping).
This is Port Restricted Cone NAT (not full-cone), but simultaneous-open hole-punching
works with it — both sides' outbound packets create conntrack entries whose reply
directions match each other's inbound packets.

## Root Cause: Endpoint Cycling Alignment

### Observed behavior (from events.log, BuildBuddy invocation `2146bc18`)

**Timeline:**

- `05:17:35` (t+0s): VPS COSI watches established, sees 3 affiliates
- `05:17:38` (t+3s): VPS→NAT2 peer goes `up` (endpoint `192.168.50.3:51820`)
- `05:18:08` (t+33s): VPS→NAT1 peer goes `up` (endpoint `192.168.50.1:51820`)
- `05:17:49` (t+14s): NAT2 COSI watches established
- `05:18:07` (t+32s): NAT2→VPS goes `up`
- `05:18:13` (t+38s): NAT1 COSI watches established, NAT1→VPS already `up`
- `05:18:13` (t+38s): NAT1→NAT2 stuck at `unknown`, endpoint `[fec0::5054:ff:feab:1]:51820`
- `05:18:37` through `05:21:38`: WireGuard link reconfigured every ~30s on both NAT
  nodes (endpoint cycling), but NAT1↔NAT2 **never transitions to `up`**

**Final state at 5-minute timeout:**

```text
vm-vps:  ready=true identity=true peers=2(up=2) affiliates=3 probes=0
vm-nat1: ready=true identity=true peers=2(up=1) affiliates=3 probes=0
vm-nat2: ready=true identity=true peers=2(up=1) affiliates=3 probes=0
```

Hub-spoke works. Peer-to-peer does not.

### Why hub-spoke works but peer-to-peer doesn't

VPS is directly reachable on the Internet segment (`192.168.50.2`). When NAT1 sends a
WireGuard handshake to VPS, Router-A masquerades it but VPS receives it directly — no
reciprocal conntrack needed. The first endpoint tried works.

For NAT1↔NAT2, both routers do masquerade. NAT hole-punching requires **both sides to
send to each other's correct public endpoint within the conntrack timeout window**. This
creates a timing dependency that doesn't exist for hub-spoke.

### The endpoint cycling problem

Each NAT node discovers 4 endpoints for the other peer via the discovery service:

| Endpoint                                    | Source                           | Reachable from other NAT? |
| ------------------------------------------- | -------------------------------- | ------------------------- |
| `10.0.2.15:51820`                           | Management NIC (QEMU user-mode)  | No — per-VM isolated      |
| `192.168.60.2:51820` / `192.168.70.2:51820` | Private LAN IP                   | No — behind NAT           |
| `[fec0::5054:ff:feab:1]:51820`              | IPv6 link-local                  | No — not routable         |
| `192.168.50.1:51820` / `192.168.50.3:51820` | Public IP (from discovery Hello) | **Yes**                   |

Only 1 of 4 endpoints works. The ManagerController's endpoint cycling:

1. Sets endpoint, state → `unknown`
2. After `EndpointConnectionTimeout` (15s) with no handshake → state → `down`
3. Next reconcile (up to 30s later) → `ShouldChangeEndpoint()` returns true → picks next
4. Per endpoint: ~15s timeout + up to ~30s reconcile wait = **~45s**
5. Full cycle through 4 endpoints: **~180s**

For NAT hole-punching, both sides must be sending to each other's correct endpoint
**simultaneously**. Since endpoint cycling is independent on each side, the probability
of alignment on any given 30s reconcile interval is roughly `(1/4) × (1/4) = 1/16`.
Expected time to alignment: ~8 cycles × 30s = ~240s, but with high variance.

With a 5-minute (300s) timeout, convergence is possible but unreliable. With the
original 900s Bazel timeout, it would eventually work — but 900s is unacceptable for
a test that should take <3 minutes.

### Why the flat test passes

All endpoints are on the same L2 segment, so **every** endpoint works. The
ManagerController's first endpoint try succeeds immediately. No cycling needed.

## Endpoint harvesting verification

The endpoint harvesting and re-announcement pipeline is correct:

1. VPS's `EndpointController` creates `kubespan.Endpoint` resources for NAT peers ✓
2. VPS's `DiscoveryController` reads them via `buildOtherEndpoints()` ✓
3. VPS publishes via `SetLocalData(affiliate, otherEndpoints)` ✓
4. Discovery service distributes them to NAT nodes ✓

However, the harvested endpoints (`192.168.50.1`, `192.168.50.3`) are already present
in the self-reported affiliate data (from the discovery service's public IP detection
in the Hello response). So endpoint harvesting doesn't add new information in this
topology — the nodes already know the correct endpoints. The problem is purely the
cycling timing with 3 wrong endpoints in the list.

## Note on `Persistent: true` masquerade

`NF_NAT_RANGE_PERSISTENT` provides **endpoint-independent mapping** (same source port
reused regardless of destination) but NOT endpoint-independent filtering. Linux
masquerade with `Persistent` is Port Restricted Cone NAT (RFC 4787). The
simultaneous-open technique works because each side's outbound packet creates a
conntrack entry whose reply direction matches the other side's inbound packet.

## Fix

The root fix is to reduce the number of wrong endpoints so the correct one is tried
sooner. Options:

1. **Filter unreachable endpoints from PeerSpec** — remove management NIC IPs
   (`10.0.2.15`), private LAN IPs not routable from the peer, and link-local IPv6.
   This reduces from 4 endpoints to 1-2, making alignment near-instant.
2. **Prioritize public/harvested endpoints** — put them first in the endpoint list
   so they're tried before private IPs.

The upstream Talos `PeerSpecController` already applies endpoint filters (removing
obviously-local addresses). The test topology exposes this because QEMU's management
NIC and IPv6 link-local create extra unreachable endpoints that wouldn't exist in a
real deployment with proper interface filtering.
