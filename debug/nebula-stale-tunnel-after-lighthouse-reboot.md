# Nebula: Stale Tunnel After Lighthouse Reboot

## Status: Unresolved (needs upstream bug report)

## Problem

When both nebula lighthouses are rebooted (new session keys), non-lighthouse peers
never re-establish tunnels. The peer's nebula process believes the tunnels are still
alive and continues sending encrypted packets with old session keys. The lighthouses
silently drop these packets (wrong session), but the peer never detects the failure.

## Symptoms

- `ping` to lighthouse nebula IPs: 100% packet loss
- Nebula logs: `Attempt to relay through hosts [10.42.0.1 10.42.0.2]` (thinks tunnels
  are alive, tries to relay through them)
- No `Handshake message sent` to lighthouses — nebula isn't trying to re-handshake
- `Refusing to handshake with myself` errors (NAT hairpin, unrelated noise)
- TX dropped on `nebula1` tun interface: billions of packets

## Why nebula doesn't detect the failure

1. UDP socket is up — packets are being sent at the transport level
2. Tunnel state says "established" — a handshake completed before the reboot
3. Lighthouse queries (`interval=10`) are sent but encrypted with old session keys
4. The rebooted lighthouse silently drops them (can't decrypt, wrong session)
5. Nebula has no application-level keepalive with acknowledgment — it doesn't
   distinguish "packets sent but peer can't read them" from "packets received"
6. `punchy` only helps with NAT traversal, not stale session detection

## Repro

1. Have a working nebula mesh with 2 lighthouses + 1 non-lighthouse peer
2. Reboot both lighthouses (or restart nebula on both)
3. Observe: the non-lighthouse peer never re-handshakes with the lighthouses
4. The mesh is dead until the peer's nebula is also restarted

## Workaround

Restart nebula on all non-lighthouse peers after lighthouse reboot:

```bash
sudo systemctl restart nebula
```

## Impact

This caused a cluster outage on 2026-03-30. VPS lighthouse nodes were rebooted to
recover from OOM. Nebula on wyrm2 (non-lighthouse) didn't detect the stale tunnels.
Cross-node pod networking was dead. Took ~3 hours to identify as a nebula issue
(initially attributed to Cilium/etcd).

## TODO

- [ ] File upstream issue at <https://github.com/slackhq/nebula/issues>
- [ ] Consider adding a cron/systemd timer that periodically checks lighthouse
      reachability and restarts nebula if tunnels are stale
