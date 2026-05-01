# 5G Modem — Foxconn DW5934e (SDX72)

**Goal**: Google Fi internet on the tablet.

**Current state (2026-04-30)**: Fully declarative. FCC unlock, modem
enable, and Google Fi connection all happen automatically via the NixOS
module <nix/nixos/hosts/rugged/foxconn-wwan.nix>. Works alongside WiFi
(IPv6 `never-default` prevents cellular from hijacking IPv6 traffic).
**Throughput is currently capped at ~7.3 KB/s by Google Fi carrier QoS**
because the modem IMEI `356398950074094` is not registered on the Fi
account; ICMP and registration are unaffected. Same throttle observed on
both eSIM (2026-04-20) and physical SIM (2026-04-30) — see "Lift the
Google Fi throttle" TODO below.

## Where to find what

| Topic                                | File                                          |
| ------------------------------------ | --------------------------------------------- |
| Status, TODOs, what to do next       | this file                                     |
| Hardware specs, NixOS config         | <esim.md> §Hardware, §NixOS Configuration     |
| SIM inventory + slot setup           | <esim.md> §SIM Inventory, §eSIM Slot Setup    |
| `lpac` / `mbimcli` reference cheats  | <esim.md> §lpac Commands, §Useful Diagnostics |
| FCC unlock root cause + history      | <foxflss_wwan.md> §What Works, §Watchdog      |
| eSIM provisioning & wedge debugging  | <foxflss_wwan.md> §Modem Reset Methods etc.   |
| Throughput / throttle investigations | <foxflss_wwan.md> §Physical SIM throughput    |

## Tools

`debug/rugged/modem.sh` is the single entry point for diagnostics and
SIM operations: `status`, `diagnose [--kill-wifi]`, `slot <0|1>`,
`esim {status|wipe|activate}`, `unlock`, `recover`. Run with no args
(or `--help`) for the full subcommand list.

**TODO**:

- **Lift the Google Fi QoS throttle** — complete data-only SIM
  activation at <https://fi.google.com> so the modem's IMEI
  (`356398950074094`) gets bound to the Fi account alongside the
  current ICCID `8901240270139815559`. Verify by re-running
  `debug/rugged/modem.sh diagnose` and checking that
  `curl --interface wwan0 http://speedtest.tele2.net/10MB.zip` exceeds
  ~10 KB/s and that the device appears in the Fi app device list.
  See `foxflss_wwan.md` "Physical SIM throughput" section.
- ~~Verify FCC unlock + auto-connect works from cold boot~~ — resolved
  2026-04-30: `fcc-unlock.d/105b:e11d` was failing silently (no
  `dmidecode` on the systemd PATH); fixed in `nix/packages/foxflss.nix`,
  MM's reactive unlock now fires correctly. Watchdog
  (`foxflss-watchdog.service`) added as safety net. See
  `foxflss_wwan.md` "Watchdog + dmidecode fix".
- **Try removing `foxflss-watchdog.service`** after ~1 month of zero
  fires. Verify with
  `journalctl -u foxflss-watchdog --since '30 days ago' | grep -c stuck`
  (should be 0 across boots, suspend/resume, and slot switches), then
  delete the systemd unit, `foxflss_watchdog.py`, and the
  `watchdogScript` let-binding in `foxconn-wwan.nix`. The watchdog was
  built before we found the dmidecode root cause and turned out never
  to have been the actual unlock path; it's defense-in-depth against
  MM giving up on a future transient FoxFlss failure (per upstream
  contract, MM doesn't retry the script after one failure).
- Investigate suspend/resume behavior (`mhi_pci_suspend` returns
  EBUSY, error -16). FoxFlss repo includes
  `mm-suspend-resume-options.conf` and `--test-quick-suspend-resume`
  MM flag.
- Investigate weak signal (9% vs 92% observed manually). Observed on
  2026-04-19: after automatic connection, `signal quality: 9%` and
  `access tech: lte` despite phone on same Google Fi subscription
  showing 4/5 bars next to it. Manually, 5G NR at 92% was achieved.
  Possible causes: RF calibration data not loaded
  (`/opt/foxconn/data/DW5934e_RF.dat`), FCC unlock timing in
  automated flow, or modem registering on weak LTE band instead of 5G
  NR. Check: `mmcli -m 0 --signal-setup=5 && sleep 6 && mmcli -m 0 --get-signal`
- **Long-term: drop the closed-source `FoxFlss` binary**. Once nixpkgs
  ships libqmi ≥ 1.38.0 (currently 1.36.0), upstream MM's
  `fcc-unlock.available.d/105b` script can do the job via the FOX
  service (`qmicli --fox-set-fcc-authentication`). The FOX service
  (0xE3) is confirmed working on our SDX72 —
  `qmicli --fox-get-firmware-version` returned
  `FDE2.F0.0.0.1.2.TO.003.062`. Track the libqmi bump in nixpkgs and
  rewrite `fcc-unlock.d/105b:e11d` to call qmicli instead of FoxFlss.
  At that point the `foxflss` package, its `/opt/foxconn/data/`
  symlinks, and the dispatcher script all collapse. The watchdog
  remains separate-cleanup (see TODO above).
