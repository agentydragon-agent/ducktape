# Nebula/VXLAN MTU: corrected model + measurements (2026-06-08)

## TL;DR

The Cilium pod MTU was `1412`, derived from a **wrong overhead model**. Cilium VXLAN
rides **inside** the Nebula tunnel (nested, not parallel), and `nebula1`'s tun MTU was at
its default **1300** — so full-size pod packets (1412 + 50 VXLAN = 1462) exceeded 1300 and
had to fragment / PMTUD-clamp. Fixed by raising `nebula1` to 1420 and lowering Cilium to 1370.

## The stack (verified via `cilium-dbg status`)

Cilium routing mode is `Tunnel [vxlan]`; VXLAN endpoints are the node `InternalIP`s, which
are the Nebula `10.42.x` addresses. So a pod packet is VXLAN-encapsulated and the result is
routed out `nebula1`, which encapsulates again onto `eno1`:

```text
pod packet ──+50 VXLAN──> [must fit nebula1 tun MTU] ──+60 Nebula──> [must fit eno1 1500]
```

The old `cilium-values.yaml` comment computed `1500 − 50 − 38 = 1412` as if VXLAN and Nebula
added 88 **in parallel**. They don't — they **stack**, and the 38 was also wrong.

## Measurements

Ran from a `hostNetwork` netshoot pod on `ovh-ns103656` (source `eno1` = 147.135.39.162).

### Underlay path MTU (DF ping between node public IPs)

| Path                                                       | 1500-byte DF frame | Result   |
| ---------------------------------------------------------- | ------------------ | -------- |
| cross-/24 → ovh-ns104963 (147.135.104.16)                  | payload 1472       | **PASS** |
| same-/24 hairpin → ovh-ns103711 (147.135.39.176, via .254) | payload 1472       | **PASS** |

The OVH inter-node underlay carries a full **1500**, including the same-/24 `.254` hairpin.
(No jumbo above 1500 — that's vRack-only, unavailable on Kimsufi.)

### Current Nebula tun ceiling

`ping -M do` over `10.42.0.17`: payload 1272 (frame 1300) **PASS**, 1273 **FAIL** → tun MTU
is exactly 1300 (Nebula default; never set in `nebula.tf`).

### Nebula overhead (tcpdump on eno1, udp/4242)

A 1300-byte inner IP packet produced an outer **UDP payload of 1332** → + 8 (UDP) + 20 (IP)
= **1360 on the wire**. So Nebula overhead = **60 bytes** exactly:

| Component         | Bytes  |
| ----------------- | ------ |
| Nebula header     | 16     |
| AES-GCM auth tag  | 16     |
| UDP header        | 8      |
| Outer IPv4 header | 20     |
| **Total**         | **60** |

## Corrected configuration

```text
eno1 (underlay)   1500   measured ceiling (hard; no jumbo on Kimsufi)
nebula1 tun MTU   1420   1420 + 60 = 1480  (20-byte margin under 1500)
Cilium / pod MTU  1370   1370 + 50 = 1420  (fits nebula1 exactly)
```

- Hard max for the stack: `nebula1 = 1440`, `MTU = 1390` (exact-fit, 1440 + 60 = 1500).
  We left a 20-byte underlay margin instead of running committed config at the ceiling.
- Applied in `cluster/terraform/main/cilium-values.yaml` (`MTU: 1370`) and `nebula.tf`
  (`tun.mtu = 1420`). These are infra-managed (OpenTofu + Cilium/Nebula machine config),
  **not Flux** — rolling them out restarts Cilium and reloads Nebula across nodes, so do it
  in a maintenance window, not a hot reconcile.

## Caveat: roaming nodes

This assumes a 1500 underlay. `rugged` (roaming laptop on cellular) has a much smaller path
MTU (~1162, see `cluster/debug/2026-06-02-tofu-apply-hangs-from-rugged-mtu.md`). A single
global Cilium MTU can't satisfy both a 1500 datacenter underlay and a cellular path; the fix
for roaming nodes is TCP MSS clamping / MTU probing, out of scope here. 1370 does not fix
rugged, but does not make it worse than the previous 1412.
