# Foxconn DW5934e WWAN Investigation

Live investigation log for the Foxconn DW5934e WWAN modem setup on the Dell Rugged 12 running NixOS.

## Hardware

- Foxconn DW5934e (SDX72) — PCI `105b:e11d`
- Firmware: `FDE2.F0.0.0.1.2.TO.003.062`, carrier config: `T-mobile` rev `0A010503`
- Communicates via MBIM through `mbim-proxy` (abstract socket `@mbim-proxy`)
- Platform ID `0D67` (Dell Rugged), detected via `dmidecode`
- Device nodes: `/dev/wwan0mbim0` (MBIM), `/dev/wwan0at0` (AT, unresponsive),
  `/dev/wwan0qcdm0` (QCDM/diagnostic, not useful for eSIM)
- **SIM slots**: slot 1 = physical micro-SIM (inside battery compartment), slot 2 = eSIM (eUICC)
- **Physical SIM slot location**: remove battery, pull SIM slot cover outward. Gold contacts
  face up, notched corner aligned. Accepts micro-SIM (nano-SIM with adapter works).
  See: Dell KB article 000214805
- Modem IMEI: `356398950074094`

## What Works (as of 2026-04-20)

- **FCC unlock** via `fcc-unlock.d`: modem typically boots with `power state: on` so this
  rarely fires, but the script is wired up correctly.
- **RF calibration** (`FoxFlss -f Check_RF_SSKU`): PASSES when modem is in clean state.
  Calibration data persists in modem NVRAM — does not need to be re-run unless firmware
  is wiped. However, RF cal does NOT meaningfully improve throughput (see below).
- **MTU fix**: `ipv6.method=disabled` in NM profile drops IPv6 minimum MTU floor (RFC 2460
  requires 1280 for IPv6), allowing `gsm.mtu=1200` to take effect. Path MTU ceiling on
  Google Fi is ~1256B. With MTU 1200, TLS appconnect went from 3.7s → 0.14s.
- **NM dispatcher script** on `wwan0 up`: wired up to run `FoxFlss -f Check_RF_SSKU` via
  `systemd-run` (transient unit `foxflss-rf-cal.service`). Fires after bearer is fully
  established.

## Root Cause: Incomplete eSIM Activation (found 2026-04-20)

### Summary

The eSIM profile in the modem was **never fully activated** with Google Fi. The profile
was downloaded to the eUICC chip but the carrier-side provisioning was never completed.
Google Fi's app shows only the Pixel 6 phone — the laptop/modem is not registered as
a device on the account. T-Mobile's network allows the unactivated SIM to register and
get minimal data service, but applies severe QoS throttling (~30 kbps TCP, ~7.5 KB/s
effective throughput).

### eSIM Identity

| Field      | Value                                          |
| ---------- | ---------------------------------------------- |
| IMSI       | `310240277530456` (MCC/MNC 310/240 = T-Mobile) |
| ICCID      | `8901240270175304567`                          |
| EID        | `89033023427100000000053696008750`             |
| GID1       | `4276`                                         |
| SIM slot   | slot 2 (eSIM), slot 1 (physical) empty         |
| Modem IMEI | `356398950074094`                              |

### Evidence Chain

1. **Google Fi app** shows only the Pixel 6 (IMEI [redacted]). The modem's
   IMEI `356398950074094` is not listed. No data-only SIM/device exists on the account.

2. **SIM IMSI operator `310240`** (T-Mobile direct) differs from the **network
   registration operator `310260`** (Google Fi). Normal for Google Fi MVNO, but
   combined with absence from the Fi app, indicates an incomplete activation.

3. **TCP traffic is shaped to ~30 kbps** while ICMP ping flows normally at 40-60ms.
   TCP RTT is consistently 320-550ms (vs 40-60ms ICMP), with 36% packet reordering.
   This differential treatment is characteristic of carrier-level QoS throttling on
   unauthorized/unactivated devices.

4. **Throughput identical across all protocols and configurations tested**:
   - IPv4 vs IPv6: same ~7.5 KB/s
   - HTTP vs HTTPS: same
   - cubic vs BBR congestion control: same
   - LTE-only vs LTE+5G: same (on LTE)
   - Single vs parallel connections: same
   - Different servers (Tele2, Google CDN): same

5. **Phone with worse signal works fine**: Phone at -119 dBm RSRP on LTE in same
   location has normal throughput. Modem at -110 dBm RSSI gets 7.5 KB/s. Rules out
   signal/coverage as cause.

### Fix: eSIM Re-provisioning (2026-04-20)

New Google Fi data-only eSIM obtained from `fi.google.com` (web UI, not app —
the app only offers physical SIM kits). The web flow provides an eSIM QR code.

**Steps completed:**

1. Decoded QR to LPA string:
   `LPA:1$sm-v4-007-a-gtm.pr.go-esim.com$TY93BCW699ZG4WBL3Z8YDWAF05GDUO4D`

2. Used `lpac` with MBIM backend to access eUICC (key: **`LPAC_APDU_MBIM_UIM_SLOT=2`**
   was required — without it, lpac tries slot 1 which is empty and fails with
   "no channel response received").

3. Downloaded new profile — all GSMA RSP steps succeeded:
   - New ICCID: `8901240270177439031`
   - Provider: Google Fi, name: Google

4. Disabled old profile (ICCID `8901240270175304567`) — success.

5. Enabled new profile (ICCID `8901240270177439031`) — success.

6. **MBIM session broke after profile switch** — "SelectFailed" on all subsequent
   lpac operations. This is expected: eUICC profile switch triggers a SIM reset,
   which invalidates all MBIM UICC channels. The modem needs a power cycle (reboot)
   to cleanly load the new profile.

**Current state (pre-reboot):** MM still shows old ICCID because the modem hasn't
reloaded the SIM. The eUICC has the new profile enabled internally.

**After reboot, verify:**

```bash
# 1. Check new SIM identity
mmcli -m 0 | grep -E 'iccid|imsi|operator'
# Expected: iccid=8901240270177439031, operator=Google Fi

# 2. Lock to LTE (5G NR unusable at primary location)
mmcli -m 0 --set-allowed-modes=4g

# 3. Connect
nmcli connection up "Google Fi"

# 4. Test throughput — this is the critical test
ping -I wwan0 -c 5 8.8.8.8
curl --interface wwan0 -4 -o /dev/null -sm 20 \
  -w "speed: %{speed_download} B/s\ntime: %{time_total}s\n" \
  http://speedtest.tele2.net/1MB.zip

# 5. Check TCP RTT vs ICMP (the smoking gun metric)
# Start download in background, then check TCP state:
curl --interface wwan0 -4 -o /dev/null -sm 15 http://speedtest.tele2.net/1MB.zip &
sleep 3 && ss -tnei dst speedtest.tele2.net | grep -E 'rtt|delivery|ooo'
# If TCP RTT ≈ ICMP RTT (not 10x higher), the throttle is gone.

# 6. If throughput still bad, check Google Fi app — does the modem
#    now appear as a device on the account?
```

**If the activation code expired** (profile downloaded but Google Fi backend
rejected it), get a new QR from `fi.google.com` and repeat. The `lpac` workflow
is proven to work on this modem — the full cycle takes ~2 minutes.

**eUICC profile inventory (as of 2026-04-21):**

| #   | ICCID                 | Provider  | State       | Class       |
| --- | --------------------- | --------- | ----------- | ----------- |
| 1   | `8901240270176681898` | Google Fi | **enabled** | operational |

All old profiles (GSMA test, two previous Google Fi attempts) have been deleted.
The current profile was downloaded from activation code
`LPA:1$sm-v4-007-a-gtm.pr.go-esim.com$N68E5CFZDWH07L815MXG7VJ5EO0W5J11`.

**Pending**: Reboot needed for MM to see the enabled profile. After reboot,
verify throughput and check whether Google Fi app shows the device.

## Modem Reset Methods (what works, what doesn't)

The modem is a separate computer (Qualcomm SDX72 SoC) with its own firmware.
The Linux kernel communicates with it over PCIe/MHI/MBIM but cannot directly
control the modem's internal state. Different reset methods affect different
layers:

### MHI driver unbind/rebind — clears MBIM UICC state after profile ops

```bash
systemctl stop ModemManager
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/unbind
sleep 3
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/bind
sleep 8
# lpac can now access the eUICC — MM must stay stopped
```

Resets the MHI channels and MBIM UICC state, clearing the "SelectFailed"
error that occurs after profile switch operations (disable/enable/delete of
enabled profile all trigger SIM reset → stale MBIM channel).

**Works after**: profile disable, profile delete, profile enable.
**Does NOT work after**: profile download — download leaves the ISD-R
(eSIM management applet) in a deeper wedged state that persists across
MHI rebinds. See "Post-download wedge" below.

### Bringing modem operational (no reboot)

After MHI rebind, modem is in `power state: low` (FCC locked). MM reports
`esim-without-profiles` / `failed`. To bring it up:

```bash
# MM must run (for mbim-proxy), even if modem is in failed state
systemctl start ModemManager && sleep 10
# FCC unlock (needs mbim-proxy)
FoxFlss && sleep 5
# Restart MM — now sees the profile, completes init
systemctl restart ModemManager
```

### Post-download wedge (CRITICAL)

After `lpac profile download` completes, the modem's MBIM stack becomes
**completely unresponsive**. ALL MBIM operations time out — not just ISD-R
(SelectFailed), but even basic `--query-device-caps`. The modem's firmware
is alive (dmesg shows MHI power-on after rebind) but its MBIM service
processor is wedged.

**Nothing clears this except a full system reboot:**

| Method                        | Resets PCIe? | Resets MHI? | Clears post-download wedge?   |
| ----------------------------- | ------------ | ----------- | ----------------------------- |
| `systemctl restart MM`        | no           | no          | no                            |
| MHI driver unbind/rebind      | no           | yes         | **no**                        |
| PCIe device remove/rescan     | yes          | yes         | **no**                        |
| PCIe Function Level Reset     | partial      | yes         | **no**                        |
| `soc_reset` sysfs trigger     | yes          | yes         | **no**                        |
| `mmcli --reset`               | no           | no          | **no**                        |
| `mbimcli --ms-set-uicc-reset` | n/a          | n/a         | parser broken in libmbim 1.32 |
| **System reboot**             | **yes**      | **yes**     | **yes**                       |

The `soc_reset` sysfs at `/sys/devices/.../mhi0/soc_reset` is supposed to
reset the Qualcomm SoC, and dmesg confirms it re-enumerates the MHI device
(`Power on setup success`, ports re-attach). But the modem firmware's MBIM
service does not recover — opens still time out. This suggests the modem's
MBIM processor is in a state that survives even SoC-level reset, and only
a full power cycle (PCIe slot power off during system shutdown) clears it.

### Implication for eSIM provisioning

The post-download wedge means eSIM provisioning requires one reboot:

1. **Before reboot**: wipe old profiles, download new profile (lpac works
   until the download command completes, then MBIM wedges)
2. **Reboot**: clears the wedge, modem reads the new profile
3. **After reboot**: send notification (`lpac notification process`),
   bring modem online (FoxFlss + MM restart)

There is no way to avoid this reboot with the current DW5934e firmware.

### Recommendation: use physical SIM

The eSIM provisioning path on this modem is unreliable (firmware wedges,
requires reboots, Google Fi backend doesn't receive installation
notification automatically). **Use a physical SIM in slot 1 (micro-SIM,
battery compartment)** for production use. eSIM is experimental only.

### What does NOT reset the modem's UICC/SIM subsystem

All of these were tried and failed to clear the post-download wedge:

- **`systemctl restart ModemManager`** — re-probes but modem firmware state persists
- **PCIe device remove/rescan** (`echo 1 > .../remove && echo 1 > /sys/bus/pci/rescan`)
  — re-enumerates PCI device but doesn't reset modem firmware
- **PCIe Function Level Reset** (`echo 1 > /sys/bus/pci/devices/0000:71:00.0/reset`)
  — resets PCIe link but modem firmware persists state
- **`mbimcli --ms-set-uicc-reset`** — broken parameter parser in libmbim 1.32.0,
  rejects all values (`disabled`, `enabled`, `0`)
- **Double MHI rebind** — no better than single
- **Longer sleep times** (up to 30s between steps) — no effect

### Full modem restart without reboot — MHI rebind + FoxFlss + MM restart

After enabling a new eSIM profile via lpac, the modem is in `failed` /
`power state: low` (FCC locked, MM sees `esim-without-profiles`). To bring
it fully operational **without a system reboot**:

```bash
# After lpac enable completes:

# 1. MHI rebind to reset MBIM state
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/unbind
sleep 3
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/bind
sleep 5

# 2. Start MM — modem will be in failed/low state, but mbim-proxy runs
systemctl start ModemManager
sleep 10

# 3. FCC unlock via FoxFlss (needs mbim-proxy from step 2)
export PATH="/nix/store/wg8dv8x56avxinns71n4mqqnj90jybbg-foxflss-1.0.15/bin:$PATH"
# (or use the foxflss package path from nixos config)
FoxFlss

# 4. Restart MM — now sees the enabled profile, completes full init
sleep 5
systemctl restart ModemManager
# Modem should now be in connected/registered state
```

The key insight: MM must be running (for mbim-proxy) before FoxFlss can
unlock the modem. But MM's first probe fails with `esim-without-profiles`
because the modem hasn't read the eUICC yet. After FoxFlss powers up the
modem, restarting MM triggers a fresh probe that now sees the profile.

### Recommended workflow for eSIM profile changes

```bash
# 1. Stop MM
systemctl stop ModemManager

# 2. MHI rebind (clears MBIM state for lpac)
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/unbind
sleep 3
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/bind
sleep 8

# 3. lpac operations (can chain multiple without rebinding)
LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac profile list
LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac profile download -s <smdp> -m <matching-id>
LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac profile enable <iccid>

# 4. If enable triggers SelectFailed on subsequent commands, MHI rebind again

# 5. Bring modem operational (no reboot needed!)
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/unbind
sleep 3
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/bind
sleep 5
systemctl start ModemManager && sleep 10
FoxFlss && sleep 5
systemctl restart ModemManager
```

Note: `lpac profile download` may time out during `es10b_load_bound_profile_package`
("Transaction timed out") but still partially install the profile. If the next
download attempt fails with `install_failed_due_to_iccid_already_exists_on_euicc`,
the profile IS installed — just enable it.

### What does NOT bring the modem out of failed/low state

- **MHI rebind alone** — resets MBIM UICC channels (lpac works) but modem
  stays in `power state: low` with FCC lock
- **`mmcli -m 0 --reset`** — accepted by MM ("successfully reseted") but
  MM re-probes and hits `esim-without-profiles` again
- **PCIe FLR** — no effect on modem power state
- **Running FoxFlss without MM** — fails with `Check mbim-proxy failed`
  (FoxFlss needs mbim-proxy which only runs when MM is active)

## Google Fi Data-Only eSIM Activation Gap (2026-04-21)

eSIM profile downloads succeed (GSMA RSP handshake completes, profile
written to eUICC, modem registers on Google Fi / T-Mobile). However,
**Google Fi's backend does not recognize the device** — it does not appear
in the Google Fi app or fi.google.com device list.

The result: the modem connects and registers, but data is throttled to
~30 kbps TCP (7.5 KB/s effective) by carrier-side QoS. ICMP ping works
normally at 50-60ms.

### What we've confirmed

- Multiple profile downloads (3 different ICCIDs) all have the same throttle
- IPv4 and IPv6 both throttled identically
- Different congestion controls (cubic, BBR) make no difference
- The QR code / activation code from fi.google.com web UI works for
  downloading the profile but doesn't complete carrier-side activation
- Google Fi app only shows the Pixel 6 phone, never the laptop modem

### Likely cause: missing GSMA installation notification

After an eSIM profile download, the GSMA SGP.22 spec requires the LPA
(Local Profile Assistant) to send an **installation notification** back
to the SM-DP+ server. This tells the carrier "profile was installed
successfully on this eUICC." Without it, the carrier backend never
registers the device.

The Google Fi Android app sends this automatically. `lpac` does NOT send
it automatically — it must be done explicitly:

```bash
# After download, list pending notifications:
lpac notification list
# Send each pending notification to the SM-DP+ server:
lpac notification process <sequence-number>
```

We never ran these commands. This is almost certainly why:

- Google Fi doesn't show the device in the app
- The carrier applies QoS throttling (treats unconfirmed profiles as
  unauthorized)

### ISD-R channel wedging after download

`lpac profile download` wedges the modem's ISD-R (eSIM management)
MBIM UICC channel. After download completes, ALL tools that need the
ISD-R fail with SelectFailed:

- `lpac` (any command) — "no channel response received: SelectFailed"
- `mbimcli --ms-set-uicc-open-channel` (ISD-R AID) — "SelectFailed"

But non-ISD-R MBIM UICC queries still work:

- `mbimcli --ms-query-uicc-application-list` — succeeds, shows USIM/ISIM

Nothing clears this state except a full reboot:

- MHI driver unbind/rebind — no effect after download
- PCIe FLR — no effect
- PCIe remove/rescan — no effect
- MM restart cycles — no effect
- `mmcli --reset` — no effect

The ISD-R channel wedging means `lpac notification process` cannot run
until after a reboot. This is a firmware limitation of the DW5934e (SDX72).

Note: MHI rebind DOES clear SelectFailed in other scenarios (after profile
disable/delete). It specifically fails to clear it after a download
operation — the download leaves the ISD-R in a deeper stuck state.

### Complete activation recipe

```bash
# Phase 1: download (ISD-R channel will wedge after this)
systemctl stop ModemManager && sleep 2
# MHI rebind
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/unbind
sleep 3
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/bind
sleep 8
# Download (auto-enables on empty eUICC)
LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac profile download -s <smdp> -m <matching-id>

# Phase 2: reboot to clear ISD-R wedge
reboot

# Phase 3: after reboot — send notification + bring modem up
systemctl stop ModemManager && sleep 2
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/unbind
sleep 3
echo 0000:71:00.0 > /sys/bus/pci/drivers/mhi-pci-generic/bind
sleep 8
# Send installation notification to Google Fi
LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac notification list
LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac notification process <seq-number>
# Bring modem up
# (MHI rebind → MM start → FoxFlss → MM restart)
```

### Fallback: physical SIM

If eSIM provisioning proves unreliable: order free Google Fi "5G Data Only
SIM Kit" ($0.00), insert micro-SIM in battery compartment slot (slot 1).
No eSIM provisioning needed.

## Resolved Issues

### Unusable Throughput Investigation (2026-04-20)

Extensive investigation ruled out all host-side causes before identifying the eSIM
activation as root cause. See evidence chain above.

### Observations During Investigation (reference)

- **RSSI-only signal reporting**: `mmcli --signal-get` returns only RSSI, no
  RSRP/RSRQ/SINR. `mbimcli --query-signal-state` confirms `RSRP/SNR info: 'n/a'`.
  SDX72 firmware limitation.
- **RF calibration resets mode lock**: `FoxFlss -f Check_RF_SSKU` resets allowed modes
  to `3g, 4g, 5g; preferred: 5g`. Must re-lock with
  `mmcli -m 0 --set-allowed-modes=4g` after RF cal.
- **5G NR unusable at primary location**: 0% signal quality, 93-1374ms latency spikes.
  LTE-only mode required. Mode lock survives reboots.
- **IPv6-only bearer rejection**: Cell sometimes rejects IPv4-only bearers with
  `Ipv6OnlyAllowed`. NM retries and gets IPv4 on next attempt.
- **AT port unresponsive**: `/dev/wwan0at0` does not respond to AT commands while MM
  is running. AT passthrough via `mmcli --command` requires `--debug` mode on MM
  startup. `mbimcli` via nix-shell works for MBIM queries.

## eSIM Provisioning from Linux

### Tools

- **`lpac`** (v2.3.0+): Open-source eUICC/LPA tool. Has native MBIM backend (added
  v2.2.0, Jan 2025). Foxconn T99W175 (same family as DW5934e) documented as
  MBIM backend = SUCCESS in lpac compatibility table.
- **`mbimcli`** (libmbim 1.32.0+): Has UICC Low Level Access commands:
  `--ms-set-uicc-open-channel`, `--ms-set-uicc-close-channel`,
  `--ms-set-uicc-apdu`, `--ms-query-uicc-atr`, `--ms-query-uicc-application-list`
- **`qmicli`**: Can tunnel QMI over MBIM (`--device-open-mbim`), has `--uim-get-card-status`
  but no high-level eSIM download commands.

### lpac Environment Variables

```bash
LPAC_APDU=mbim
LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0
LPAC_APDU_MBIM_UIM_SLOT=2          # 1-based; slot 2 = eSIM
LPAC_APDU_MBIM_USE_PROXY=1         # needed when ModemManager is running
```

### lpac Commands

```bash
# List profiles (MM stopped, no proxy needed):
sudo systemctl stop ModemManager
sudo LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac profile list

# Download new profile:
sudo LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 \
  lpac profile download \
  -s sm-v4-007-a-gtm.pr.go-esim.com \
  -m TY93BCW699ZG4WBL3Z8YDWAF05GDUO4D

sudo systemctl start ModemManager
```

### What Failed (2026-04-20)

- `lpac` with `LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0` — "no channel response
  received: Failure". Tried with MM stopped, with/without proxy. **Did NOT set
  `LPAC_APDU_MBIM_UIM_SLOT=2`** — this may have been the issue (eSIM is slot 2,
  default is slot 1 which is empty).
- `mbimcli --ms-open-channel=1` — wrong flag name. Correct flag is
  `--ms-set-uicc-open-channel` with parameters
  `application-id=A0000005591010FFFFFFFF8900000100,selectp2arg=4,channel-group=1`
  (AID is ISD-R applet for eSIM management).
- AT commands via `/dev/wwan0at0` — port unresponsive. Foxconn modems on WWAN
  subsystem do not expose traditional AT serial. AT backend documented as FAIL
  for T99W175 in lpac compatibility table.

### Fallback: Physical SIM

If eSIM provisioning fails from Linux: order free Google Fi "5G Data Only SIM Kit"
($0.00), insert micro-SIM in battery compartment slot (slot 1). No eSIM provisioning
needed.

## Previous Issue: 5G NR Unusable (2026-04-19)

Modem defaulted to 5G NR NSA with 0% signal quality and latency spikes up to 1374ms.
Manual `mmcli -m 0 --set-allowed-modes=4g` fixed latency to 47-67ms but throughput
remained poor (~6-7.5 KB/s). The mode lock survives reboots.

## Previous Issue: MBIM Session Exhaustion (2026-04-19)

Setting `autoconnect-retries = 0` (unlimited) in the NM profile caused NM to hammer
the modem with connection attempts on profile change. Each failed attempt leaked an
MBIM CID session. After ~272 attempts, all bearers failed with "Unknown error". Only
a full power cycle (reboot) clears the modem firmware's MBIM session table. PCIe
remove/rescan is insufficient.

## FoxFlss Tool Dependencies

FoxFlss shells out to several tools that must be on `PATH`. The systemd transient unit
has a minimal PATH, so all must be supplied explicitly via `lib.makeBinPath`:

- **`dmidecode`**: reads system SKU for platform detection (`0D67` = Dell Rugged).
- **`pgrep`** (procps): checks if `mbim-proxy` process is running. Without it, FoxFlss
  always reports `Check mbim-proxy failed` regardless of proxy state.
- **`tar`** (gnutar): extracts RF calibration data from
  `/opt/foxconn/data/DW5934e_RF.dat` (a `.tar.gz` archive) to
  `/var/tmp/DW5934e/RF_Files/`.
- **`gzip`**: needed by `tar` to decompress the `.dat` archive. Without `gzip`, `tar`
  exits with `Cannot exec: No such file or directory`.
- **`grep`** (gnugrep), **`sed`** (gnused), **`awk`** (gawk), **`coreutils`**: used to
  parse `dmidecode` output and perform platform ID string matching.

## MBIM Session Limit Pitfall (CRITICAL)

The DW5934e has a hard limit on simultaneous MBIM CID sessions. When FoxFlss fails
mid-run (e.g., during an NM reconnect), it leaks the MBIM CIDs it opened — they remain
in modem firmware until MM restarts and closes all sessions.

After multiple failed FoxFlss attempts, the modem hits its session limit. Subsequent
FoxFlss runs fail with:

```
ModuleTypeCheck: Retry to fail connect device: /dev/wwan0mbim0 for the 20 time
Current platform:0D67 do not support FccLock!
```

The `do not support FccLock` message is a **false negative** from connection failure, NOT
a real platform check result. `0D67` DOES support FccLock.

**Fix**: `systemctl restart ModemManager` — this closes all MBIM sessions and resets the
proxy. FoxFlss will work again after ~8s sleep.

## What We Tried That Didn't Work

### `foxflss-init` systemd service (`After=ModemManager.service`)

Discarded. Problems:

1. During `nixos-rebuild switch`, the NM profile change causes NM to reconnect cellular.
   MM is mid-reconnect when the service starts. FoxFlss leaks MBIM CIDs from each failed
   attempt.
2. `switch-to-configuration` restarts the service on each rebuild (even with
   `restartIfChanged=false`, failed units get restarted).
3. After several failed attempts, MBIM session limit hit → FoxFlss broken until MM
   restart.

### Wait-for-proxy poll loop in the service

`ss -xH | grep -q mbim` returns true immediately (MM always has proxy connections) but
FoxFlss still fails because the modem is mid-reconnect at a MBIM protocol level, not
just at the proxy socket level.

## NM Dispatcher Approach (Current)

Wired as `networking.networkmanager.dispatcherScripts` in `foxconn-wwan.nix`.

Script fires on `wwan0 up` and runs via `systemd-run --no-block --collect`:

```
FoxFlss && sleep 5 && FoxFlss -f Check_RF_SSKU
```

### MBIM warm-up requirement

`Check_RF_SSKU` fails at the MBIM connect step if run immediately after bare `FoxFlss`.
The vendor's Ubuntu setup avoids this because `fcc-unlock.d` (bare `FoxFlss`) runs before
`FoxFlss.service` (Check_RF_SSKU), flushing stale MBIM CIDs and leaving the device in a
clean state. On this NixOS system, `fcc-unlock.d` never fires (modem boots with
`power state: on`). The warm-up must be done explicitly: bare `FoxFlss` + `sleep 5` before
`Check_RF_SSKU`.

Confirmed in log: `Check_RF_SSKU: Failed to connect device` when called immediately
after FCC unlock (CrcCompatibilityCheck had just disconnected). After adding the
warm-up, `Check_RF_SSKU: PASS`.

### systemd-run flags

`--collect` is critical. Without it, the transient unit stays in `failed` state after a
failure. On the next `wwan0 up` event, `systemd-run` fails with:

```
Unit foxflss-rf-cal.service was already loaded
```

and FoxFlss never runs for that connection.

`--no-block`: NM waits for dispatcher scripts to finish. Backgrounding via `systemd-run`
prevents the connection from appearing active while FoxFlss is running.

### Passing the script to systemd-run

`systemd-run ... -- sh -c '...'` fails in the minimal service environment (`sh` not on
PATH). Use `pkgs.writeShellScript` to generate an absolute-path shell script, and pass it
directly as the `ExecStart` argument.

**Pending validation**: confirm dispatcher fires and FoxFlss succeeds on a clean cold boot
(no zombie MBIM sessions from previous failed attempts).

## `/opt/foxconn/data/` Setup

FoxFlss hardcodes `/opt/foxconn/data/{DW5932e,DW5934e}_RF.dat`. On NixOS (read-only
root), these are created as symlinks via `systemd-tmpfiles.rules` pointing into the nix
store (`foxflss` derivation's `share/foxflss/`).

## Vendor Reference

`foxconn-pc/fii_linux` on GitHub. Their `FoxFlss.service`:

- `ExecStart=FoxFlss -f Check_RF_SSKU` (only `Check_RF_SSKU`, no bare `FoxFlss`)
- `After=ModemManager.service`
- `Restart=on-abort` (not `on-failure` — only restarts on crash, not graceful exit 1)
- `StandardError=null`
- Bare `FoxFlss` (FCC unlock) is in separate `fcc-unlock.d` scripts, not the service.
