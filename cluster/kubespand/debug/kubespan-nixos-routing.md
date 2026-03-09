# KubeSpan NixOS Worker Routing Debug Log

## Problem

k8s-worker-test (NixOS, 10.0.243.53 on Proxmox LAN) cannot route traffic
through KubeSpan WireGuard tunnel to VPS control plane nodes.

## Current state

**ICMP through KubeSpan works** (after flushing iptables).
**TCP through KubeSpan fails** (HAProxy can't connect to VPS:6443).

## Observations (chronological)

### Phase 1: Initial diagnosis

- WireGuard handshakes work (all peers "up", recent handshakes)
- nftables chains (`kubespan_outgoing`, `kubespan_prerouting`) installed correctly
  with VPS IPs in destination sets
- ip rule `32500: fwmark 0x40/0x60 lookup 180` present
- Table 180: `default dev kubespan mtu 1420` present
- `ip route get 5.78.43.147 mark 0x40` → `dev kubespan table 180` (correct)
- WireGuard transfer counters increase both directions (data flows)
- tcpdump on kubespan shows ICMP echo replies AND TCP SYN-ACKs arriving

### Phase 2: What doesn't drop packets

- **rpfilter**: DROP counter stayed at 0 after ping
- **NixOS firewall**: flushed to accept-all, still failed
- **`networking.firewall.enable = false`**: rebuilt image, still failed
- **iptables counter forensics**: all 225 packets passed through entire INPUT chain
  (CILIUM_INPUT → KUBE-FIREWALL → nixos-fw) with zero drops anywhere
- **Cilium TC BPF**: `tc filter show dev kubespan ingress` — empty (no eBPF on kubespan)

### Phase 3: Nuclear iptables flush

- Flushed ALL iptables (filter, mangle, raw, nat), set all policies ACCEPT
- Flushed nftables talos table
- **Ping to VPS worked via ens18 (internet, not KubeSpan)** — proves direct connectivity OK
- Restarted kubespand (reinstalls nftables chains only, iptables stays flushed)
- **ICMP ping to VPS through KubeSpan: WORKS** (2/2, ~32ms)
- **ICMP ping to Proxmox CP (10.2.1.1) through KubeSpan: FAILS**
- **TCP to VPS:6443 through KubeSpan: FAILS** (HAProxy Layer4 timeout)

### Phase 4: Current state summary

After iptables flush + kubespand restart:

- ICMP to VPS IPs: **works** (goes through KubeSpan based on fwmark)
- TCP to VPS IPs: **fails**
- ICMP to Proxmox IPs (10.2.x.x): **fails**

## Hypotheses

### H1: conntrack interaction with fwmark (HIGH probability)

TCP requires conntrack to match SYN-ACK to original SYN. ICMP echo/reply
matching is simpler. With iptables flushed but conntrack module still loaded,
conntrack may be confusing the connection state because:

- Outgoing SYN gets mark 0x40 via nftables OUTPUT chain
- SYN is sent through kubespan (WireGuard encrypts, mark becomes 0x20)
- WireGuard's encrypted UDP packet exits via ens18 with mark 0x20
- Reply arrives as encrypted UDP on ens18, WireGuard decrypts
- Decrypted SYN-ACK arrives on kubespan with mark 0x00
- conntrack may not associate the SYN-ACK with the original SYN because
  the marks differ, or because the packet arrived on a different interface

Evidence: conntrack showed all TCP entries stuck in SYN_RECV (SYN sent,
SYN-ACK arrived but not matched to complete handshake).

### H2: Proxmox ping failure is a different bug

10.2.1.1 is reachable via the VLAN (Proxmox LAN), not via internet. The
KubeSpan tunnel to Proxmox nodes goes through the local mcast network.
This failing could be rpfilter on the Proxmox side, or a WireGuard
AllowedIPs issue.

### H3: `type route` nftables OUTPUT chain marks but re-routing fails for TCP

The `kubespan_outgoing` chain has `type route` (not `type filter`). This
triggers a routing re-lookup after the mark is set. For ICMP, re-routing
works. For TCP, the re-lookup may interact with conntrack's route cache
or socket binding.

### H4: The VPS Hetzner firewall drops TCP from unexpected source IPs

The ping works but TCP doesn't. The Hetzner firewall may have rules that
allow ICMP but restrict TCP to known source IPs. The packet arrives at
the VPS with src=10.0.243.53 (a private IP), which may be dropped by
Hetzner's firewall for TCP but allowed for ICMP.

BUT: this doesn't explain why conntrack entries show SYN_RECV (which
means SYN-ACK was sent back). If Hetzner dropped the TCP SYN, there
would be no SYN-ACK at all.

## QEMU test results

All 4 probes pass in the QEMU environment:

- IPv6 ULA ICMP ✓
- IPv4 peer eth1 ICMP ✓
- IPv6 ULA TCP ✓
- IPv4 peer eth1 TCP ✓

The QEMU VMs have no iptables, no Cilium, no conntrack complexity.

## Root cause found

**kubespand does not add the node's own IP to the kubespan interface.**

When a reply packet arrives on `kubespan` with `dst=10.0.243.53`, the kernel
needs to find this as a "local" address reachable via the receiving interface.
Without it, the kernel returns "Invalid cross-device link" and drops the packet.

ICMP worked because ICMP echo reply is handled by `icmp_rcv()` which has different
routing validation than TCP's socket lookup path.

**Fix:** `sudo ip addr add 10.0.243.53/32 dev kubespan` — after this, ALL traffic
works (ICMP, TCP, all peers, API server accessible).

**Talos equivalent:** Talos's KubeSpan manager writes an `AddressSpec` COSI resource
that adds the node's routed addresses to the kubespan/wg-kubespan interface.
kubespand skips this because it uses direct netlink instead of COSI.

## Fix implemented

In `controller_manager.go`, after creating the WireGuard interface and adding the ULA
address, kubespand now adds the node's non-ULA routed addresses (from
`discovery.RoutedNodeAddresses()`) to the kubespan interface as secondary `/32` or
`/128` addresses. This ensures the kernel accepts reply packets arriving on kubespan.

The QEMU test now enables `ip_forward=1` and `rp_filter=2` (matching real NixOS
environment) and verifies both ICMP and TCP probes to peer eth1 IPs through KubeSpan.

## Phase 5: Verification after manual fix

After `ip addr add 10.0.243.53/32 dev kubespan`:

- Ping all 4 peers: ✓ (VPS ~25-31ms, Proxmox ~1ms)
- TCP to VPS:6443: ✓ (CONNECTED)
- API healthz via HAProxy: ✓ (returns 401 = auth needed, but TCP works)
- HAProxy backends: UP (2/3, cp3 doesn't exist)
