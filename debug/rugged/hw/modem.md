# 5G Modem — Foxconn DW5934e (SDX72)

**Goal**: Google Fi internet on the tablet.

**Current state (2026-04-18)**: FCC lock **solved** using Foxconn `FoxFlss` binary.
Modem registers on Google Fi (5G NR, 92% signal). Bearer connects successfully via
`mmcli --simple-connect`. Remaining: NixOS declarative setup (package FoxFlss, wire
as `fcc-unlock.d` script, configure NM or systemd-networkd for automatic IP).

See <esim.md> for full FCC unlock details, sequencing, and remaining work.

**Next steps**:

1. Package `FoxFlss` for NixOS and wire via `networking.modemmanager.fccUnlockScripts`
2. Fix NetworkManager integration (NM sees `wwan0mbim0` as `gsm / unavailable`)
   or use systemd-networkd for automatic IP configuration on `wwan0`
3. Investigate suspend issue (`mhi_pci_suspend` returns EBUSY, error -16)

**Suspend issue**: `mhi_pci_suspend` returns EBUSY. FoxFlss repo includes
`mm-suspend-resume-options.conf` and `--test-quick-suspend-resume` MM flag.
