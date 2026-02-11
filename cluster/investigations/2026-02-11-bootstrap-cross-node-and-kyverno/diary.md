# Bootstrap Cross-Node Convergence and Kyverno Webhook Timeouts

**Date**: 2026-02-11, continued 2026-02-10
**Status**: Fix committed (`91e801346`), awaiting verification via bootstrap

## Problem

During bootstrap, kyverno webhook timeouts block HelmRelease installations:

```text
failed calling webhook "validate.kyverno.svc-fail": context deadline exceeded
```

Affected HelmReleases: tofu-controller, ingress-nginx, trust-manager.

## Investigation Timeline

### Bootstrap #1 (2026-02-11 ~01:00 UTC)

- cert-manager-trust and ingress-nginx lacked `dependsOn: kyverno`
- Webhook timeouts occurred because kustomizations deployed concurrently with kyverno
- Fix: added `dependsOn: kyverno` to both (commit `52a58797`)
- Also observed transient cross-node DNS failure (source-controller on pve-cp-0
  couldn't resolve github.com via CoreDNS on vps-cp-0). Self-resolved after
  ~5-10 minutes once VXLAN tunnels converged.

### Bootstrap #2 (2026-02-11 05:11 UTC)

With dependsOn fix applied, kyverno was verified ready before dependents started.
**Same webhook timeout still occurred:**

```text
T+0s    kyverno HelmRelease install succeeded
T+3s    kyverno kustomization health check passed (VWC exists, deployment ready)
T+4s    tofu-controller HelmChart created (core kustomization started)
T+21s   tofu-controller INSTALL FAILED — kyverno webhook timeout
```

The dependency was met. Kyverno WAS ready. The failure was elsewhere.

### Evidence: Cross-Node Networking

**TLS handshake EOF** — kyverno admission-controller logs:

```text
05:13:27 TLS handshake error from 10.244.0.60:38118: EOF
05:14:19 TLS handshake error from 10.244.0.60:45058: EOF
05:14:46 TLS handshake error from 10.244.0.60:58668: EOF
```

10.244.0.x is vps-cp-1's pod CIDR. The API server on vps-cp-1 tried to reach
the kyverno webhook on pve-worker-0 and got TLS EOF — the VXLAN tunnel between
those nodes was unstable.

**KubeSpan asymmetry** — from vps-cp-0:

| Peer               | State       | Traffic                        |
| ------------------ | ----------- | ------------------------------ |
| talos-vps-cp-1     | up          | 43MB                           |
| talos-pve-cp-0     | up          | 28MB                           |
| talos-pve-worker-0 | **up**      | **56KB** (barely established)  |
| talos-pve-worker-0 | **unknown** | 0 (phantom — never handshaked) |

pve-worker-0 had two KubeSpan entries due to dual-identity from ISO-to-disk reboot.
Traffic was orders of magnitude less than other peers.

**Cilium health was fine by the time we checked** (~8 min after failure):

```text
vps-cp-1 → pve-worker-0: ICMP OK (32ms), HTTP OK (28ms)
```

Confirmed transient — the tunnel stabilized, but too late for the initial
HelmRelease install attempt.

**No resource pressure**: All nodes 0-4% CPU, 4-24% memory. Pure network transient.

## Root Cause Analysis

### Layer 1: Single-Pod Cilium Health Check

`bootstrap.py` convergence check only exec'd `cilium-health status` on the first
cilium pod. If that pod was on vps-cp-0, it verified connectivity FROM vps-cp-0
but not FROM vps-cp-1. The broken path (vps-cp-1 → pve-worker-0) was not tested.

**Fix**: commit `91e801346` — check from ALL cilium pods with structured JSON.

### Layer 2: KubeSpan AllowedIP Routing Black Hole (the deeper issue)

Source code analysis of Talos KubeSpan reveals a mechanism that can cause
**persistent routing failures** for up to 30 minutes during bootstrap.

#### How KubeSpan tunnel establishment works

**State machine** (every 30s reconciliation in `ManagerController`):

1. Read WireGuard device state (handshake times, endpoints, bytes)
2. Calculate peer state based on time since `LastEndpointChange`:
   - **0–15s**: "unknown" (grace period for new endpoint)
   - **15s–275s**: "down" if no handshake since endpoint change
   - **275s+**: "up" if handshake within 275s, else "down"
3. If peer is DOWN: rotate to next endpoint (round-robin), reset to "unknown"
4. Apply new WireGuard config

Source: `internal/app/machined/pkg/adapters/kubespan/peer_status.go`

**AllowedIP routing** (`ManagerController`, `manager.go:328`):

```go
if cfgSpec.ForceRouting || peerStatus.State == kubespan.PeerStateUp {
    for _, prefix := range peerSpec.AllowedIPs {
        allowedIPsBuilder.AddPrefix(prefix)
    }
}
```

`ForceRouting` defaults to `false`. Only peers in UP state get their AllowedIPs
added to nftables routing rules. Traffic to IPs NOT in any peer's AllowedIPs
falls through to default gateway routing.

#### The phantom peer AllowedIP collision

`PeerSpecController` builds `PeerSpec` resources from discovery affiliates. It has
overlap detection (`peer_spec.go:135-158`): when two peers claim overlapping
AllowedIPs, the **later-processed peer's IPs get subtracted**.

During bootstrap, each VPS node has two affiliates (phantom + real) with
**overlapping AllowedIPs** (same node IPs like 10.2.2.1). Which peer wins depends
on iteration order of a Go map — **non-deterministic**.

**If phantom wins the AllowedIPs:**

1. PeerSpecController assigns 10.2.2.1 to phantom's PeerSpec, strips it from real
2. Phantom has dead WireGuard key → handshake fails → state goes DOWN within 15s
3. ManagerController builds nftables: phantom is DOWN so 10.2.2.1 NOT in routing rules
4. Real peer is UP but its AllowedIPs were stripped — 10.2.2.1 also NOT in routing rules
5. **Result**: Traffic to 10.2.2.1 goes to default gateway → fails (private IP unreachable from VPS)
6. VXLAN tunnel to pve-worker-0: black hole

**If real peer wins the AllowedIPs:** Everything works normally.

#### Why this oscillates

PeerSpecController is event-driven (not periodic). It re-runs when any affiliate
changes. The real peer's affiliate updates periodically via the discovery service
streaming connection. Each re-evaluation rebuilds the `peerIPSets` map from
scratch with potentially different Go map iteration order.

So connectivity to a node can **oscillate** between working and broken across
PeerSpecController cycles, depending on which identity wins the AllowedIP race.

#### Implications for our convergence check

The full-mesh Cilium health check (commit `91e801346`) WILL detect the broken
path when it occurs. But:

1. **Check might pass on a lucky cycle** where real peer won AllowedIPs, then
   the next PeerSpecController cycle phantom wins → connectivity breaks AFTER
   our check passed
2. **600s timeout may be insufficient** — phantom TTL is ~30 minutes. If the
   phantom consistently wins, connectivity won't stabilize within our timeout
3. **No point-in-time check can guarantee stability** while phantom peers exist

### What Was NOT the Bug

| Component               | Bug?           | Notes                                          |
| ----------------------- | -------------- | ---------------------------------------------- |
| Kyverno VWC healthCheck | No             | Correctly gates on VWC existence               |
| `dependsOn: kyverno`    | No             | core/ingress-nginx already have it             |
| Kyverno internal certs  | No             | VWC creation timing is correct                 |
| Single-pod Cilium check | Yes            | Only checked from first pod                    |
| KubeSpan dual-identity  | **Root cause** | AllowedIP collision creates routing black hole |

## Committed Fix (partial)

Commit `91e801346`: Full-mesh Cilium health check with structured JSON.

This is necessary but may not be sufficient. It catches the symptom (broken
connectivity) but can't prevent the underlying AllowedIP oscillation from
phantom peers.

## What Would Actually Fix This

### Option 1: Eliminate dual identity (rescue+dd boot)

Boot Hetzner VPS via rescue mode, `dd` Talos disk image directly. Single Talos
boot = single identity = no phantom peers = no AllowedIP collision.

```text
1. hcloud_server created with image=debian-12 (no ISO)
2. Enable rescue mode → reboot into rescue Linux
3. In rescue: download Talos hcloud disk image, dd to /dev/sda
4. Disable rescue, reboot → Talos boots from disk (first and only boot)
5. STATE partition created, identity generated once
6. talos_machine_configuration_apply → config updated, no reinstall
```

Two reboots but only ONE Talos boot. Eliminates the problem entirely.

### Option 2: Wait for phantom TTL expiry

Add a step in bootstrap.py that waits until KubeSpan peer count equals exactly
`node_count - 1` (no phantoms). This requires waiting up to 30 minutes.

### Option 3: Upstream Talos change

Config field for pre-generated KubeSpan identity, so it survives ISO-to-disk
reboot. Requires Talos project change.

## Technical Reference

### KubeSpan State Machine Constants

| Constant                    | Value | Source                                |
| --------------------------- | ----- | ------------------------------------- |
| `PeerReconcileInterval`     | 30s   | `manager.go:39`                       |
| `EndpointConnectionTimeout` | 15s   | `peer_status.go`                      |
| `PeerDownInterval`          | 275s  | `wireguard.go` (180+5+90 per WG spec) |
| Discovery affiliate TTL     | 30min | `discovery_service.go:40`             |

### KubeSpan Peer State Zones

```text
T0 = LastEndpointChange

[T0 → T0+15s]    No handshake: UNKNOWN   Handshake: UP
[T0+15s → T0+275s]  No handshake: DOWN   Handshake: UP
[T0+275s → ∞]       LastHandshake > 275s ago: DOWN   Otherwise: UP
```

### Network Architecture

```text
Internet → VPS public IPs → ingress-nginx (hostNetwork) → backend pods
                    ↕ KubeSpan WireGuard (UDP 51820)
         Proxmox private IPs (10.2.x.x) → worker pods
                    ↕ Cilium VXLAN (UDP 4789)
              Pod-to-pod traffic across nodes
```

### Node Layout

| Node               | Location | Pod CIDR      | Node IP      |
| ------------------ | -------- | ------------- | ------------ |
| talos-vps-cp-0     | Hetzner  | 10.244.1.0/24 | 5.78.106.249 |
| talos-vps-cp-1     | Hetzner  | 10.244.0.0/24 | 5.78.43.147  |
| talos-pve-cp-0     | Proxmox  | 10.244.4.0/24 | 10.2.1.1     |
| talos-pve-worker-0 | Proxmox  | 10.244.3.0/24 | 10.2.2.1     |

### KubeSpan Dual-Identity Boot Sequence (VPS)

```text
1. hcloud_server created with ISO
2. Talos boots from ISO → STATE on tmpfs → identity A registered with discovery
3. talos_machine_configuration_apply → install to disk → reboot
4. Talos boots from disk → new STATE → identity B registered
5. Identity A persists in discovery for ~30 min TTL → phantom peer
```

Proxmox nodes boot from disk image directly — single identity, no phantom.

### Source Code References

- `internal/app/machined/pkg/controllers/kubespan/manager.go` — WireGuard reconciliation loop
- `internal/app/machined/pkg/controllers/kubespan/peer_spec.go` — AllowedIP overlap detection
- `internal/app/machined/pkg/adapters/kubespan/peer_status.go` — State machine, endpoint rotation
- `internal/app/machined/pkg/controllers/kubespan/identity.go` — Identity generation
- `pkg/machinery/resources/kubespan/config.go` — ForceRouting (default false)
- `api/v1/health/models/connectivity_status.go` (Cilium) — Health JSON structure
