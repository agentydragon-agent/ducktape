# 5G Modem — Foxconn DW5934e (SDX72)

**Goal**: Google Fi internet on the tablet.

**Current state (2026-04-18)**: Fully declarative. FCC unlock, modem enable, and
Google Fi connection all happen automatically via NixOS module
<nix/nixos/modules/foxconn-wwan.nix>. Works alongside WiFi (IPv6 `never-default`
prevents cellular from hijacking IPv6 traffic).

See <esim.md> for FCC unlock details, sequencing, and research notes.

**TODO**:

- Verify FCC unlock + auto-connect works from cold boot (only tested after
  `nixos-rebuild switch` so far)
- Investigate suspend/resume behavior (`mhi_pci_suspend` returns EBUSY, error -16).
  FoxFlss repo includes `mm-suspend-resume-options.conf` and
  `--test-quick-suspend-resume` MM flag.
