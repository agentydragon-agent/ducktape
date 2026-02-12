# Bootstrap Cross-Node Convergence and Kyverno Webhook Timeouts

**Date**: 2026-02-11, continued 2026-02-10
**Status**: Bootstrap stalled at ~18/64 Ready. VXLAN packet drops from vps-cp-0 causing webhook timeouts. MTU mismatch suspected.

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

## Committed Fixes

### Fix 1: Full-mesh Cilium health check (`91e801346`)

Check from ALL cilium pods with structured JSON, not just first pod.

### Fix 2: Packer snapshot boot (eliminates dual identity)

Implemented Option 1 from below. VPS nodes now boot from a pre-baked Hetzner
snapshot containing Talos on disk. Single Talos boot = single identity = no
phantom peers.

**Packer flow**: rescue mode → `dd` Talos disk image → snapshot → servers boot
from snapshot. Idempotency check skips Packer build if matching snapshot exists.

Commits: `ad303ef25` (Packer snapshot + idempotency), `a1e5483f9` (Helm boolean
workarounds, superseded).

### Fix 3: Replace Helm provider with CLI (`2a23d8eda`)

Helm provider v3 has unfixed plan consistency bugs with OpenTofu — computed
fields (`status`, `id`, `metadata`) return null during plan but non-null during
apply. OpenTofu's stricter plan check rejects this. PR hashicorp/terraform-provider-helm#1739
is stalled.

Replaced both `helm_release` resources (Cilium, hcloud-csi) with
`null_resource` + `helm` CLI. Removed helm provider entirely.

### Fix 4: Cilium health stderr/stdout separation

The Python kubernetes client's `stream()` with `_preload_content=True` (default)
merges stdout and stderr into one string. `cilium-health status -o json` writes
errors to stderr (e.g., `health.sock: no such file or directory` during startup),
corrupting the JSON output. Fix: use `_preload_content=False` and read
`STDOUT_CHANNEL` separately.

This was causing the "Cilium health unparseable" message that hid the real
connectivity status.

### Fix 5: Remove unnecessary Cilium restart

Bootstrap was doing a rolling restart of Cilium immediately after `helm install`
"to refresh BPF state for API servers." But Cilium was just installed — there's
no stale BPF state. The restart added ~1-2 minutes of unnecessary downtime and
caused transient `health.sock: no such file or directory` errors during the
convergence check.

## Bootstrap Attempt Results

### Attempt 8 (2026-02-11 ~01:10 UTC) — Infrastructure succeeds

First successful infrastructure deployment after all fixes:

- Packer snapshot: pre-existing, skipped build
- VPS servers: booted from snapshot (single identity confirmed)
- Cilium + hcloud-csi: deployed via `helm` CLI (no provider bugs)
- All 4 nodes Ready
- Cross-node convergence: passed after Cilium restart settled (~7 min)
- KubeSpan: 3/3 expected peers up (previously saw 9 due to phantoms — now clean)
- **Kyverno deployed without webhook timeouts** — the original problem is fixed

### Attempt 9 (2026-02-11 ~01:23 UTC) — Re-run with stderr fix

Idempotent re-run to test stdout/stderr fix. Infrastructure layer: 0 changes
(already applied). Convergence check now shows actual errors:

```text
01:24:56 stdout='' stderr='Error: Cannot get status: ... health.sock: no such file or directory'
01:25:12 Cilium: talos-pve-cp-0 → vps-cp-0 host/http: connection refused
01:26:15 Cross-node networking converged
```

Previously this loop showed "unparseable" with no diagnostic info for 10+ minutes.

Flux kustomization convergence in progress (19/64 Ready at 2 min 54s).

## Original Options Analysis (for reference)

### Option 1: Eliminate dual identity (rescue+dd boot) — IMPLEMENTED

See Fix 2 above.

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

### Attempt 9 continued — VPS DNS failure blocks convergence

Bootstrap reached 36/64 Ready then stalled. Root blocker: **VPS nodes cannot resolve
external DNS** — containerd image pulls fail with `lookup ghcr.io on 127.0.0.53:53: server misbehaving`.

**Diagnosis chain:**

1. cert-manager challenges all `pending` — SOA lookup for `_acme-challenge.*.allegedly.works`
   returns `SERVFAIL` from public DNS (8.8.8.8, 1.1.1.1)
2. PowerDNS zones not created — `powerdns-operator` pod on VPS in `ImagePullBackOff` (DNS failure)
3. `dns-records` terraform stuck "Initializing" — tofu-controller can't run terraform
4. `sso-secrets` terraform stuck "Initializing"
5. Kyverno webhook timeouts for headscale/website — cross-node webhook calls failing

**Three distinct DNS layers affected:**

| Layer                 | Symptom                                                                                   | Root Cause                                                                                                                                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Host DNS (127.0.0.53) | containerd image pulls fail                                                               | `forwardKubeDNSToHost` intercepts kube-dns VIP queries via Talos host-dns proxy, but interaction with Cilium VXLAN breaks resolution                                                                                     |
| CoreDNS pods          | `forward . /etc/resolv.conf` → 169.254.116.108 (link-local, unreachable from pod network) | Talos HostDNS binds to `169.254.116.108` ([PR #9200](https://github.com/siderolabs/talos/pull/9200)) and writes it to resolv.conf; this link-local on `lo` is unreachable from non-hostNetwork pods through Cilium VXLAN |
| Public DNS            | SERVFAIL for allegedly.works                                                              | PowerDNS zone not serving because operator can't pull image                                                                                                                                                              |

**Fix 6 (committed `347c36d8`)**: CoreDNS Corefile — changed `forward . /etc/resolv.conf`
to `forward . 1.1.1.1 8.8.8.8` in `k8s/core/coredns-custom.yaml`.

**Fix 7 (committed `3d170032`)**: VPS Talos machine config — added explicit
`nameservers = ["1.1.1.1", "8.8.8.8"]` and set `forwardKubeDNSToHost = false`
in `terraform/01-infrastructure/hetzner-nodes.tf`.

**Why `forwardKubeDNSToHost = false`**: Even after patching nameservers to public
DNS via live `talosctl` patch, host-dns at 127.0.0.53 still returned SERVFAIL.
The feature intercepts pod DNS queries to the kube-dns ClusterIP and routes them
through the host-dns proxy. With Cilium VXLAN, this breaks in a way that's not
fixed by upstream DNS changes alone. Disabling it lets pods use CoreDNS directly
(which forwards to 1.1.1.1/8.8.8.8).

**Correction (post-investigation)**: The `169.254.116.108` address in resolv.conf
was **not** provided by Hetzner DHCP. Hetzner's actual DNS resolvers are
`213.133.100.100`, `213.133.99.99`, `213.133.98.98`. The `169.254.116.108`
address is a [Talos-chosen constant](https://github.com/siderolabs/talos/pull/9200)
for HostDNS (ASCII `116='t'`, `108='l'`), introduced in Talos 1.8 to replace the
previous approach of allocating the 9th service CIDR IP. Talos writes this address
into the node's resolv.conf when `forwardKubeDNSToHost` is enabled. The real issue
is that this link-local address on `lo` is unreachable from non-hostNetwork pods
through Cilium VXLAN tunnels — not a Hetzner-specific problem. See
[issue #9196](https://github.com/siderolabs/talos/issues/9196) for the original
bug report that prompted the link-local change.

**Current state**: Fixes committed and pushed to `devel`. Full destroy → bootstrap
needed to apply VPS machine config changes, but Proxmox is unreachable (not on
home network). Targeted `terraform apply` of VPS machine config resources would
work but terraform state is locked from a previous apply.

**Additional findings:**

- `buildbuddy-executor` HelmRelease `Failed` — needs Proxmox-only scheduling
  (`topology.kubernetes.io/region: proxmox`) but BuildBuddy chart likely can't
  pull images either. Separate issue.
- PowerDNS `extraSecretKeys` fix working — operator pod on pve-cp-0 (cached image)
  started successfully with both `powerdns_api_key` and `PDNS_API_KEY` keys.

### Next Steps: Strip to Talos-Recommended Defaults

See <recommendation-minimal-networking.md> for full analysis.

**Key insight**: The DNS failure and KubeSpan instability were consequences of
10+ non-default Cilium options. Talos docs and the Talos maintainer explicitly
state that KubeSpan only works reliably with default Cilium configuration. The
`bpf.hostLegacyRouting`, `forwardKubeDNSToHost=false`, and explicit `nameservers`
were workarounds for problems caused by other non-default options (`endpointRoutes`,
`hostServices`, `socketLB`, etc.) — not inherent incompatibilities.

**Proposed**: Strip Cilium to the 7 settings Talos recommends + `mtu: 1370` (to
prevent silent fragmentation from VXLAN+WireGuard double encapsulation) + hubble.
Revert all DNS workarounds to defaults. Test with diagnostic checklist. Fallback
plan ready if HostDNS still fails.

**Also discovered**: Current config has no explicit MTU, meaning every cross-node
pod packet >1370 bytes silently fragments at the KubeSpan WireGuard interface.
This likely contributed to the intermittent TCP failures and slow convergence
observed during bootstrap.

### Bootstrap After Secrets Refactoring (2026-02-11 ~19:40-20:15 UTC)

Context: Secrets migration completed (per-service Vault-backed modules replacing
centralized `sso-secrets`). Cilium already stripped to Talos-recommended defaults +
`mtu: 1370` + hubble from earlier in the day. Full destroy → bootstrap.

**Two prior bootstrap attempts failed before reaching Flux:**

1. `tofu validate` failed in 01-infrastructure — missing required providers (needed `tofu init`)
2. `tofu apply` failed — inconsistent dependency lock file (needed `tofu init -upgrade`)

**Third attempt** reached Flux and deployed kustomizations. Stalled at **~18-20/64 Ready**.

**New Terraform modules succeeded**: `authentik-token` Ready at 20:10:01,
`powerdns-secrets` Ready at 20:10:11 (the modules we just created in the refactoring).

#### Symptom: Webhook Timeouts Block Convergence

Three kustomizations stuck:

| Kustomization              | Error                                                                              |
| -------------------------- | ---------------------------------------------------------------------------------- |
| `vault-token`              | `failed calling webhook "validate.external-secrets.io": context deadline exceeded` |
| `monitoring-stack-secrets` | Same ESO webhook timeout                                                           |
| `kyverno-policies`         | `failed calling webhook "validate.kyverno.svc-fail": context deadline exceeded`    |

These are **admission webhook** timeouts during kustomize-controller dry-run.
kustomize-controller submits resources to the API server with dry-run flag;
API server calls admission webhooks; webhooks don't respond in time.

- ESO webhook: `failurePolicy: Fail`, `timeoutSeconds: 5`
- Kyverno policy webhook: `failurePolicy: Fail`, `timeoutSeconds: 10`

#### Key Finding: All Failures From vps-cp-0 Only

Checked API server audit logs on ALL 3 control plane nodes:

| Node           | IP           | Webhook timeout errors                       |
| -------------- | ------------ | -------------------------------------------- |
| talos-vps-cp-0 | 5.78.106.249 | **Many** (dozens)                            |
| talos-vps-cp-1 | 5.78.43.147  | **Zero**                                     |
| talos-pve-cp-0 | 10.2.1.1     | Early kyverno only (failOpen during startup) |

kustomize-controller runs on talos-pve-worker-0 and uses KubePrism
(`localhost:7445`) to distribute requests across API servers. When KubePrism
routes to vps-cp-0's API server, webhook calls from that API server fail.

#### Cilium BPF Service Map: Correctly Populated

Checked `cilium-dbg service list` on ALL 4 nodes. All have identical 95
service entries. Both ESO webhook and Kyverno ClusterIPs present with correct
backend pod IPs. **Not a service programming issue.**

#### Resources: Not Constrained

vps-cp-0: 8% CPU, 34% memory. No pressure.

#### Direct Connectivity Measurements from vps-cp-0

Deployed test pod (`curlimages/curl`) with `nodeSelector` pinned to vps-cp-0.
Measured ClusterIP → webhook pod connectivity:

**ESO webhook (10.107.232.172:443) — pod on talos-vps-cp-1:**

```text
attempt  1: 0.010s
attempt  2: 0.647s
attempt  3: 3.161s
attempt  4: 0.227s
attempt  5: 1.475s
attempt  6: 1.492s
attempt  7: 0.228s
attempt  8: 5.002s TIMEOUT (connect=0.000)  ← TCP SYN lost
attempt  9: 0.011s
attempt 10: 0.224s
```

**Kyverno webhook (10.98.75.10:443) — pods on vps-cp-0 + pve-cp-0 + vps-cp-1:**

```text
attempt  1: 0.009s  (local pod)
attempt  2: 5.002s TIMEOUT (connect=0.000)  ← TCP SYN lost
attempt  3: 5.002s TIMEOUT (connect=0.000)  ← TCP SYN lost
attempt  4: 0.410s  (cross-node)
attempt  5: 5.002s TIMEOUT (connect=0.000)  ← TCP SYN lost
attempt  6: 0.008s  (local pod)
attempt  7: 0.106s  (cross-node)
attempt  8: 0.007s  (local pod)
attempt  9: 0.232s  (cross-node)
attempt 10: 0.009s  (local pod)
```

**Critical observation**: `connect=0.000` on all failures means the TCP SYN
packet never received a SYN-ACK. The connection attempt was not slow — it was
completely dropped. VXLAN packets from vps-cp-0 are intermittently lost.

Fast responses (~0.008s) = local pod on same node.
Moderate responses (0.1-0.6s) = cross-node via VXLAN/KubeSpan.
Timeouts (5.002s) = cross-node where VXLAN packet was dropped entirely.

**Failure rate**: ~10-30% of cross-node connections from vps-cp-0 timeout.

#### Webhook Pod Placement

| Webhook                | Pod node                     | Pod IP                                 |
| ---------------------- | ---------------------------- | -------------------------------------- |
| ESO webhook            | talos-vps-cp-1               | 10.244.2.121                           |
| Kyverno admission (×3) | vps-cp-0, pve-cp-0, vps-cp-1 | 10.244.0.74, 10.244.1.242, 10.244.2.52 |
| kustomize-controller   | talos-pve-worker-0           | 10.244.3.23                            |

#### MTU Mismatch Suspected

Interface MTUs on vps-cp-0:

| Interface    | MTU       | Expected |
| ------------ | --------- | -------- |
| eth0         | 1500      | 1500     |
| cilium_vxlan | 1452      | **1370** |
| kubespan     | 1420      | 1420     |
| pod veths    | 1480-1500 | 1370     |
| lo           | 65536     | —        |

**Problem**: `cilium_vxlan` MTU is 1452, but `kubespan` MTU is 1420. Packets
encapsulated by VXLAN (up to 1452+50=1502 outer) exceed KubeSpan's 1420 MTU.
The kernel must fragment at the WireGuard interface, and fragments can be
silently dropped by middleboxes or reassembly failures.

Despite setting `mtu: 1370` in Cilium Helm values, the `cilium_vxlan` interface
shows 1452. This suggests the MTU setting may not have been applied correctly,
or the interface MTU calculation differs from expected (`1370 + 50 VXLAN overhead

- 32 VXLAN header = 1452`?). Needs further investigation.

Conntrack: 6524/262144 — healthy, not a conntrack exhaustion issue.

#### Leading Hypothesis

VXLAN packets from vps-cp-0 that exceed the KubeSpan WireGuard interface MTU
(1420) are being fragmented. IP fragments traversing the internet between
Hetzner VPS and home Proxmox are intermittently dropped (common behavior for
UDP fragments traversing NAT/middleboxes). This causes ~10-30% of cross-node
TCP connections from vps-cp-0 to fail completely at the SYN level.

The fact that vps-cp-0 is the ONLY affected API server (vps-cp-1 has zero
webhook timeouts) is unexplained by this theory alone — both VPS nodes should
have identical MTU configuration. Possible explanations:

1. Different VXLAN tunnel paths (vps-cp-0 → Proxmox vs vps-cp-1 → Proxmox may
   traverse different internet paths with different fragment handling)
2. Asymmetric load — vps-cp-0 may have been handling more cross-node webhook
   calls by chance during the observation window
3. Different pod placement causing different cross-node patterns

#### Root Cause Found: `mtu` vs `MTU` (case sensitivity)

Cilium Helm chart 1.16.5 defines the MTU key as **`MTU`** (uppercase). Our
`cilium-values.yaml` had **`mtu`** (lowercase). Helm values are case-sensitive,
so the setting was silently ignored. Verified:

- `helm show values cilium/cilium --version 1.16.5` shows `MTU: 0`
- `helm get values cilium -n kube-system` shows `mtu: 1370` (user-supplied)
- `cilium-config` ConfigMap has **no** `mtu` key
- All pod veths, `cilium_vxlan`, `cilium_host` have MTU **1500** (auto-detected)

**IP fragmentation statistics confirm the problem:**

| Counter        | vps-cp-0 | vps-cp-1 |
| -------------- | -------- | -------- |
| FragOKs        | 16,458   | 8,170    |
| FragFails      | 23       | 45       |
| FragCreates    | 32,566   | 16,222   |
| ReasmReqds     | 69,556   | 50,717   |
| ReasmOKs       | 34,500   | 25,149   |
| **ReasmFails** | **556**  | **419**  |

Both nodes are heavily fragmenting (16K+ events on vps-cp-0). Hundreds of
reassembly failures on both — fragments lost in transit between VPS and Proxmox.

**Why vps-cp-0 appeared worse than vps-cp-1**: Both nodes fragment equally.
The asymmetry in webhook timeouts is likely due to which API server the
kustomize-controller happened to reach via KubePrism during the observation
window — not a per-node networking difference.

**Packet size calculation:**

```text
Pod MTU (current):     1500  ← WRONG, should be 1370
+ VXLAN overhead:      +  50  (outer IPv4: 20 + UDP: 8 + VXLAN: 8 + inner Eth: 14)
= Outer IP packet:     1550
→ kubespan MTU:        1420  (1500 - 80 WireGuard/IPv6 overhead)
→ 1550 > 1420:         MUST FRAGMENT every large cross-node packet
+ WireGuard overhead:  +  80  (outer IPv6: 40 + UDP: 8 + WG header: 32)
= Wire packet:         1500  per fragment (fits eth0)

With fix (MTU 1370):
Pod sends:             1370
+ VXLAN:               +  50  = 1420  (fits kubespan exactly)
+ WireGuard:           +  80  = 1500  (fits eth0 exactly)
→ Zero fragmentation
```

**Fix**: Changed `mtu: 1370` to `MTU: 1370` in `cilium-values.yaml`.

Sources:

- [Cilium 1.16 Helm Reference](https://docs.cilium.io/en/v1.16/helm-reference/) — `MTU` key definition
- [VXLAN overhead breakdown](https://packetpushers.net/blog/vxlan-udp-ip-ethernet-bandwidth-overheads/) — 50 bytes
- [WireGuard header sizes](https://lists.zx2c4.com/pipermail/wireguard/2017-December/002201.html) — 60 IPv4 / 80 IPv6

### Source Code References

- `internal/app/machined/pkg/controllers/kubespan/manager.go` — WireGuard reconciliation loop
- `internal/app/machined/pkg/controllers/kubespan/peer_spec.go` — AllowedIP overlap detection
- `internal/app/machined/pkg/adapters/kubespan/peer_status.go` — State machine, endpoint rotation
- `internal/app/machined/pkg/controllers/kubespan/identity.go` — Identity generation
- `pkg/machinery/resources/kubespan/config.go` — ForceRouting (default false)
- `api/v1/health/models/connectivity_status.go` (Cilium) — Health JSON structure
