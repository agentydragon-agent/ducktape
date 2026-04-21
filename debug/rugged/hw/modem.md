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
- Investigate weak signal (9% vs 92% observed manually). Observed on 2026-04-19:
  after automatic connection, `signal quality: 9%` and `access tech: lte` despite
  phone on same Google Fi subscription showing 4/5 bars next to it. Manually,
  5G NR at 92% was achieved. Possible causes: RF calibration data not loaded
  (`/opt/foxconn/data/DW5934e_RF.dat`), FCC unlock timing in automated flow, or
  modem registering on weak LTE band instead of 5G NR.
  Check: `mmcli -m 0 --signal-setup=5 && sleep 6 && mmcli -m 0 --get-signal`
