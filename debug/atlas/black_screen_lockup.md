# Atlas Black Screen Lockup — Recurring Chipset Failure

## Summary

Atlas (Proxmox host, ASUS ProArt X870E-CREATOR WIFI) has recurring system hangs (black screen, requires power-off) caused by the AMD 800 Series chipset PCIe fabric failing. The failure manifests as SATA link errors on the second AHCI controller (`ata7`–`ata10`), then escalates to the entire chipset subtree going offline — SATA, USB (xHCI), and Atlantic NIC all become inaccessible (`0xFFFFFFFF` reads), causing soft lockups and a hard hang.

Six incidents so far. SATA cable reseat on Mar 6 did **not** help — incident 3 occurred afterward with identical pattern plus USB controller death, confirming this is **not** a cable issue. Incidents 4–6 continue the pattern with increasing frequency (two hangs on Mar 10 alone).

## Recurrence Log

| #   | Onset        | Hang          | Recovery                     | Uptime before failure  | Devices affected                                            |
| --- | ------------ | ------------- | ---------------------------- | ---------------------- | ----------------------------------------------------------- |
| 1   | Feb 28 00:04 | Feb 28 ~18:05 | Mar 4 20:52 (powercycle)     | ~5h after boot         | SATA (`ata7`, `ata8`, `ata10`)                              |
| 2   | Mar 5 02:38  | Mar 5 ~06:47  | Mar 6 01:17 (powercycle)     | ~6h after boot         | SATA (`ata7`, `ata8`), Atlantic NIC, PCIe `08:08.0`         |
| 3   | Mar 7 00:01  | Mar 7 ~06:42  | Mar 7 06:54 (powercycle)     | ~23h after boot        | SATA (all 4), xHCI USB, Atlantic NIC                        |
| 4   | Mar 7 18:29  | **survived**  | Mar 9 22:36 (clean shutdown) | ~5h onset, 2.5d uptime | SATA (`ata7` only) — errors but no cascade                  |
| 5   | Mar 10 00:01 | Mar 10 ~01:04 | Mar 10 01:06 (powercycle)    | ~1.5h after boot       | SATA (`ata7`), Atlantic NIC, soft lockup                    |
| 6   | —            | Mar 10 ~06:31 | Mar 10 13:21 (powercycle)    | ~5.5h after boot       | Atlantic NIC, soft lockup (pci_mmcfg_read + aq_hw_read_reg) |

## Incident 1 — Feb 28

### Timeline

| Time         | Event                                                                                           |
| ------------ | ----------------------------------------------------------------------------------------------- |
| Feb 27 19:17 | Boot started                                                                                    |
| Feb 28 00:04 | `ata7` starts throwing `READ FPDMA QUEUED` timeouts, `SError: PHYRdyChg CommWake 10B8B LinkSeq` |
| Feb 28 06:36 | `ata8` joins with ATA bus errors (`PHYRdyChg CommWake DevExch`)                                 |
| Feb 28 06:37 | `ata7` continues with bus errors                                                                |
| Feb 28 06:40 | `ata10` starts timing out too — 3 of 4 SATA drives now failing                                  |
| Feb 28 06:45 | Kernel downgrades `ata7` link from 6.0 Gbps to 3.0 Gbps. `BadCRC`, `Handshk`, `TrStaTrns` flags |
| Feb 28 06:48 | Last SATA errors in journal. System limps along (cron, smartd, tailscaled still running)        |
| Feb 28 18:05 | Journal abruptly stops. Machine hung                                                            |
| Mar 4 20:52  | Powercycle. All drives come back clean at 6.0 Gbps, ZFS pools ONLINE, zero errors               |

## Incident 2 — Mar 5

### Timeline

| Time        | Event                                                                                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Mar 4 20:52 | Boot after powercycle. All drives up at 6.0 Gbps                                                                                                                         |
| Mar 5 02:38 | `ata7` starts with same pattern: `READ/WRITE FPDMA QUEUED` timeouts, `SError: PHYRdyChg CommWake 10B8B LinkSeq`. Hard reset recovers link at 6.0 Gbps                    |
| Mar 5 02:42 | `ata8` joins: `SError: PHYRdyChg CommWake DevExch`. Hard reset recovers                                                                                                  |
| Mar 5 06:38 | `ata7` again: same errors plus `TrStaTrns`. ZFS `delay` events on `ata-ST16000NT001-3MC101_ZYD502GM-part1` (delays 31–34s)                                               |
| Mar 5 06:43 | `ata7` escalates: **`irq_stat 0x48000008, interface fatal error`**, `SError: UnrecovData CommWake 10B8B BadCRC Handshk LinkSeq`, `error: ICRC ABRT`. Hard reset recovers |
| Mar 5 06:45 | `ata8` hard reset and re-link at 6.0 Gbps                                                                                                                                |
| Mar 5 06:47 | Network link drops (`atlantic enp12s0: link change old 100 new 0`). PCIe port `0000:08:08.0` unable to transition from D3hot to D0 — **device inaccessible**             |
| Mar 5 06:47 | **Soft lockup**: `CPU#12 stuck for 22s` in `kworker` doing `pci_mmcfg_read` → `pci_restore_ltr_state` → `pci_pm_runtime_resume`. PCI config read returns `0xFFFFFFFF`    |
| Mar 5 06:47 | Journal ends. Machine hung                                                                                                                                               |

### New observations in incident 2

- **`ata10` did not fail** this time (only `ata7` and `ata8`), but system still hung
- **PCI bus-level failure**: the hang was preceded by a PCIe device (`0000:08:08.0`) becoming inaccessible during runtime PM resume — `pci_mmcfg_read` returned all-ones (classic sign of a device/link that has dropped off the bus)
- **Network card (Atlantic/Aquantia) lost link** at the same time — this NIC is on the same PCIe root complex, suggesting the problem may extend beyond SATA to the chipset/PCIe fabric
- **`interface fatal error`** flag appeared (not seen in incident 1), indicating the AHCI controller itself flagged an unrecoverable condition
- **ZFS delay events** explicitly logged: 31–34 second I/O delays on `ata7`'s drive before the hang
- **Onset timing**: ~6h after boot (incident 1 was ~5h). Both overnight — possibly thermal buildup or a periodic background task (ZFS scrub from incident 1 may still have been running)

## Incident 3 — Mar 7

This incident occurred **after** the partial SATA cable reseat on Mar 6.

### Timeline

| Time        | Event                                                                                                                                                             |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mar 6 01:17 | Boot after powercycle. All drives up at 6.0 Gbps. Atlantic NIC up                                                                                                 |
| Mar 6 01:52 | Atlantic NIC link flap (10G → 0 → recovers) — independent NIC flakiness, not part of chipset failure                                                              |
| Mar 7 00:01 | `ata7` starts: `SError: PHYRdyChg CommWake DevExch`, `READ FPDMA QUEUED` failed. Hard reset recovers                                                              |
| Mar 7 00:05 | `ata7` again: `SError: PHYRdyChg CommWake 10B8B DevExch`, hard reset recovers                                                                                     |
| Mar 7 06:30 | `ata7` resumes: `SError: PHYRdyChg CommWake DevExch`, hard reset                                                                                                  |
| Mar 7 06:35 | `ata7` escalates: multiple READ/WRITE FPDMA failures, `SError: PHYRdyChg CommWake 10B8B LinkSeq`                                                                  |
| Mar 7 06:36 | `ata7` again: hard reset                                                                                                                                          |
| Mar 7 06:41 | **Soft lockup**: CPU#25 stuck for 26s in `pci_mmcfg_read` → `pci_restore_ltr_state` → `pci_pm_runtime_resume` (workqueue: `pm pm_runtime_work`). RAX=`0xFFFFFFFF` |
| Mar 7 06:41 | **xHCI USB controller `0000:0e:00.0` dies**: "xHCI host controller not responding, assume dead". USB devices disconnect                                           |
| Mar 7 06:41 | `ata10` joins: `SError` with **all flags set** (`0xFFFFFFFF`), WRITE FPDMA failures                                                                               |
| Mar 7 06:41 | AHCI controller `0000:11:00.0`: "AHCI controller unavailable!" (repeated)                                                                                         |
| Mar 7 06:41 | `ata9` joins: READ FPDMA failures, hard reset                                                                                                                     |
| Mar 7 06:41 | All 4 SATA ports: `failed to resume link (SControl FFFFFFFF)`, `SATA link down (SStatus FFFFFFFF SControl FFFFFFFF)` — controller completely gone                 |
| Mar 7 06:41 | **Atlantic NIC stuck**: CPU#6 soft lockup in `aq_hw_read_reg` → `aq_nic_service_task` — NIC MMIO reads hanging                                                    |
| Mar 7 06:42 | Soft lockup escalates: CPU#25 stuck 105s. More USB disconnects. Network unreachable. Journal ends                                                                 |

### New observations in incident 3

- **xHCI USB controller died** (`0000:0e:00.0`) — first time USB is affected. "not responding, assume dead"
- **All 4 SATA drives** failed (not just ata7/ata8). All returned `SStatus/SControl FFFFFFFF`
- **Atlantic NIC stuck** in MMIO register read (`aq_hw_read_reg`), causing its own soft lockup on a separate CPU
- **Partial cable reseat did not help** — incident occurred ~29h after the Mar 6 intervention. Note: only right-side mobo connectors and disk-side connectors were reseated; the 2 bottom mobo-side connectors were not touched (blocked by GPUs)
- **Onset ~23h after boot** (longer than incidents 1-2's ~5-6h), but the initial `ata7` errors at 00:01 match the previous pattern of overnight onset
- **Escalation was faster**: from first `ata7` errors to complete chipset death in ~6.5h (similar to incidents 1-2)
- **Multiple CPUs locked**: CPU#25 (`pm_runtime_work`), CPU#6 (`atlantic`), CPU#1 (`atlantic` again), CPU#25 repeated at 78s, 105s

## Incident 4 — Mar 7–9 (survived)

Boot -3: Mar 7 13:00 → Mar 9 22:36 (clean shutdown). ~2.5 days uptime — longest so far.

### Timeline

| Time        | Event                                                                                                                      |
| ----------- | -------------------------------------------------------------------------------------------------------------------------- |
| Mar 7 13:00 | Boot after powercycle                                                                                                      |
| Mar 7 18:29 | `ata7` starts: `SError: RecovData UnrecovData Proto CommWake 10B8B BadCRC Handshk LinkSeq TrStaTrns`, 4x READ FPDMA failed |
| Mar 7 18:41 | `ata7` again: `SError: CommWake 10B8B LinkSeq`                                                                             |
| Mar 7 23:00 | `ata7` again: `SError: RecovData UnrecovData CommWake 10B8B BadCRC Handshk LinkSeq`                                        |
| Mar 8 03:17 | `ata7` again: `SError: PHYRdyChg CommWake 10B8B Handshk LinkSeq`                                                           |
| Mar 8 06:33 | `ata7` again: `SError: PHYRdyChg CommWake DevExch`                                                                         |
| Mar 8 06:36 | `ata7` again: `SError: UnrecovData CommWake 10B8B BadCRC Handshk LinkSeq TrStaTrns`                                        |
| Mar 8 06:38 | `ata7` again: `SError: PHYRdyChg CommWake DevExch`                                                                         |
| Mar 8 06:39 | `ata7` last errors: `SError: CommWake 10B8B Handshk LinkSeq`                                                               |
| Mar 9 22:36 | Clean shutdown (SIGTERM, journal stopped normally)                                                                         |

### Notable

- **Did NOT escalate** to full chipset death. `ata7` had repeated errors with hard resets but the chipset PCIe fabric held.
- Only `ata7` was affected — no `ata8`/`ata9`/`ata10`, no USB, no NIC.
- All errors recovered via hard reset. System remained functional for 2.5 days.

## Incident 5 — Mar 10 (boot -2)

Boot: Mar 9 22:37 → Mar 10 ~01:04 (hung). Only ~2.5h uptime.

### Timeline

| Time         | Event                                                                                                                            |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Mar 9 22:37  | Boot after clean shutdown                                                                                                        |
| Mar 10 00:01 | `ata7` starts: `interface fatal error`, `SError: UnrecovData CommWake 10B8B BadCRC Handshk LinkSeq TrStaTrns`, READ FPDMA failed |
| Mar 10 01:03 | Atlantic NIC link drop (`link change old 2500 new 0`)                                                                            |
| Mar 10 01:03 | **Soft lockup**: CPU#8 stuck 22s in `pci_mmcfg_read` (pm_runtime_work). CPU#6 stuck 22s                                          |
| Mar 10 01:04 | CPU#8 stuck 48s. Journal ends. Machine hung                                                                                      |

### Notable

- `interface fatal error` appeared immediately on first `ata7` error (not after escalation)
- Very fast progression: ata7 errors at 00:01, hang at ~01:04 — only 1h between first error and death
- Shortest time-to-death yet

## Incident 6 — Mar 10 (boot -1)

Boot: Mar 10 01:06 → Mar 10 ~06:31 (hung). ~5.5h uptime.

### Timeline

| Time         | Event                                                                                                                                          |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Mar 10 01:06 | Boot after powercycle                                                                                                                          |
| Mar 10 01:06 | Atlantic NIC link up (2500)                                                                                                                    |
| Mar 10 06:31 | Atlantic NIC link drop (`link change old 2500 new 0`)                                                                                          |
| Mar 10 06:31 | **Soft lockup**: CPU#8 stuck 22s in `pci_mmcfg_read` → `pci_restore_ltr_state` → `pci_pm_runtime_resume` (pm_runtime_work). RAX=`0xFFFFFFFF`   |
| Mar 10 06:31 | CPU#0 stuck 22s in `aq_hw_read_reg` → `hw_atl2_shared_buffer_read_block` → `aq_nic_service_task` (atlantic workqueue) — NIC MMIO reads hanging |
| Mar 10 06:31 | Journal ends. Machine hung                                                                                                                     |

### Notable

- **No `ata7` SATA errors logged before the hang** — the first visible symptom was the Atlantic NIC losing link, immediately followed by soft lockups
- Two separate CPUs locked: CPU#8 on PCI config space read (pm_runtime_work), CPU#0 on Atlantic NIC MMIO read
- The hang occurred at the same time of day (~06:30) as incidents 2, 3, and 5's ata7 escalation
- Possible that ata7 errors occurred but weren't logged before the chipset fabric dropped entirely

## PCIe Topology of Affected Devices

All affected devices share the same root port `0000:02.1` through the AMD 800 Series chipset PCIe switch:

```
0000:02.1 (CPU PCIe root port)
  └─ 04:00.0 (PCIe switch upstream)
      └─ 05:xx (switch downstream ports)
          ├─ 08:xx (inner PCIe switch)
          │   ├─ 0a: MediaTek WiFi
          │   ├─ 0b: Intel I226-V (igc) — not affected (yet)
          │   ├─ 0c: Aquantia Atlantic NIC — STUCK in incidents 2, 3, 5, 6
          │   ├─ 0d: (empty downstream port) — FFFFFFFF in incident 2
          │   ├─ 0e: AMD xHCI USB — DEAD in incident 3
          │   └─ 0f: AMD SATA Controller #1
          ├─ 10: AMD xHCI USB #2
          └─ 11: AMD SATA Controller #2 — ata7-ata10, UNAVAILABLE in all incidents
```

## Analysis

- **Confirmed chipset-level failure**: Three different device types (SATA, USB, NIC) behind the same AMD 800 Series chipset PCIe hierarchy all fail simultaneously. This rules out SATA cables as the root cause.
- **Same escalation pattern**: `ata7` link errors → hard resets → AHCI controller unavailable → PCIe fabric returns `0xFFFFFFFF` → soft lockups → system hang
- **`ata7` is usually the canary**: first to show errors in incidents 1–5, hours before the cascade. But incident 6 had no logged SATA errors — the chipset PCIe fabric may have dropped without SATA being the first visible symptom.
- **PCI config space `0xFFFFFFFF`** across multiple devices confirms the chipset's PCIe switch or its upstream link is dropping
- **Runtime PM is the trigger for the lockup**: the soft lockup always occurs in `pci_pm_runtime_resume` → `pci_mmcfg_read`, trying to restore a device that has already fallen off the bus. The kernel spins forever waiting for a response that will never come
- **ASPM L1 is enabled** on the chipset PCIe switch (`LnkCtl: ASPM L1 Enabled`) — L1 power state transitions are a known source of PCIe link instability, especially with AMD 800 Series chipsets
- **Atlantic NIC has independent flakiness** (link flap at Mar 6 01:52 with no other symptoms), but its MMIO hangs during the lockup events are caused by the shared chipset failure, not the NIC itself
- **Frequency is increasing**: incidents 1–3 were every 1–2 days. Incidents 5–6 were back-to-back on Mar 10 (2.5h and 5.5h uptime respectively)
- **~06:30 is the witching hour**: incidents 2, 3, and 6 all had their fatal lockup around 06:30. Investigated: `apt-daily-upgrade.timer` fires at 06:00+random(60m), but the last run (06:19:18 on boot -1) completed instantly with nothing to upgrade. `locate.service` fires at 00:00 and does a full filesystem scan (coincides with midnight-onset incidents 3, 5), but doesn't explain 06:30 hangs. `cups.service` retry-loops every ~90s around 06:30 in all incidents but is benign. **No specific I/O-heavy job triggers the 06:30 crashes** — the timing correlation is likely coincidental, reflecting that most boots happen overnight and the chipset fails after ~5-6h of uptime
- SMART health: all 4 drives PASSED, zero reallocated/pending/uncorrectable sectors, temps 31–40°C
- ZFS pools: ONLINE with zero errors after every powercycle

**Conclusion**: The AMD 800 Series chipset (Promontory successor) on this ASUS ProArt X870E-CREATOR WIFI has a recurring failure where its internal PCIe fabric drops out, taking all downstream devices offline. Possible causes: chipset thermal issue, chipset firmware bug (ASPM-related?), defective chipset, or marginal power delivery to the chipset.

## Available Sensors

Installed `lm-sensors` (2026-03-10). Available readings via `asusec` ISA adapter and other hwmon drivers:

| Sensor                 | Source  | Typical value | Notes                                            |
| ---------------------- | ------- | ------------- | ------------------------------------------------ |
| CPU (Tctl)             | k10temp | ~63°C         |                                                  |
| CPU CCD1/CCD2          | k10temp | ~52–54°C      |                                                  |
| CPU (EC reading)       | asusec  | ~49°C         |                                                  |
| CPU Package            | asusec  | ~60°C         |                                                  |
| Motherboard            | asusec  | ~36°C         | Closest proxy for chipset temp (not chipset die) |
| VRM                    | asusec  | ~57°C         |                                                  |
| T_Sensor               | asusec  | -62°C         | Disconnected (no external probe)                 |
| DDR5 DIMMs ×4          | spd5118 | 45–48°C       |                                                  |
| Atlantic NIC (PHY/MAC) | enp12s0 | ~55°C         |                                                  |
| NVMe                   | nvme    | ~56°C         |                                                  |
| GPU (edge)             | amdgpu  | ~49°C         |                                                  |
| GPU vddgfx             | amdgpu  | ~1.32V        | Only voltage rails available                     |
| GPU vddnb              | amdgpu  | ~0.91V        |                                                  |
| CPU_Opt fan            | asusec  | ~720–860 RPM  | Only fan reading                                 |

**Not available:** PSU voltage rails (3.3V, 5V, 12V), chipset die temperature, chassis fans. The `asusec` driver exposes no `in*_input` channels — requires multimeter for PSU voltages.

## Scheduled Jobs Inventory

Checked as potential triggers for the recurring ~06:30 and ~00:00 hangs.

| Job                       | Schedule                  | I/O impact                   | Correlation                                                                                                  |
| ------------------------- | ------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `apt-daily-upgrade.timer` | 06:00 + random(60m)       | Heavy (apt upgrade)          | Fires in 06:00–07:00 window but last run completed instantly (nothing to upgrade). Not the trigger           |
| `apt-daily.timer`         | 06:00,18:00 + random(12h) | Moderate (apt update)        | Wide random window, not consistently at 06:30                                                                |
| `locate.service`          | 00:00 daily               | Heavy (full filesystem scan) | Coincides with midnight-onset incidents (3, 5). Was running when ata7 first errored in incident 5 (00:01:47) |
| `pve-daily-update.timer`  | 01:00 + random(5h)        | Moderate                     | Wide random window                                                                                           |
| `logrotate.timer`         | ~00:00 + random           | Light                        | Not significant                                                                                              |
| `fstrim.timer`            | Weekly (Mon)              | Moderate (SSD trim)          | Not relevant — SATA drives are HDDs                                                                          |
| ZFS scrub cron            | 2nd Sunday 00:24          | Heavy                        | Monthly only, not correlated with incident frequency                                                         |
| ZFS trim cron             | 1st Sunday 00:24          | Moderate                     | Monthly only                                                                                                 |
| `cups.service`            | Retry-loops every ~90s    | Negligible                   | Present in all 06:30 incidents but benign — just socket timeout                                              |

**Conclusion**: `locate.service` may stress the chipset at midnight but doesn't explain 06:30 hangs. The ~06:30 timing reflects typical uptime-to-failure (~5-6h) from overnight boots, not a scheduled trigger.

## Interventions Log

### Mar 6 ~17:35 — Partial cable reseat and reroute

The motherboard has 4 SATA connectors: 2 on the right side, 2 on the bottom.

**Done:**

- Reseated both SATA cables on the **right side** of the motherboard
- Reseated SATA cables on the **disk side** of all drives
- Rerouted the 2 right-side cables — they had been at a questionable 90-degree twist, now rerouted to follow a less strained path

**Not done:**

- The 2 **bottom** SATA connectors were not reseated — accessing them requires removing probably both GPUs, too inconvenient for now

**Result:** Did not help. Incident 3 occurred ~29h later with identical pattern plus USB controller death.

### Mar 10 ~13:35 — Force-disable ASPM and runtime PM on chipset devices

**Discovery:** `pcie_aspm=off` was already in `/etc/kernel/cmdline` but **had no effect** — ASPM L1 remained enabled on chipset devices `04:00.0`, `0e:00.0`, `10:00.0`, `11:00.0`. The kernel ASPM policy showed `[default]`, meaning the parameter only prevented the kernel from _adding_ ASPM, but didn't clear ASPM already enabled by BIOS/firmware.

**Done:**

- Force-cleared ASPM L1 on all chipset devices via `setpci -s $dev CAP_EXP+10.w=0000:0003` (clears bits 0:1 of Link Control register)
- Disabled PCIe runtime PM on chipset devices (`echo on > /sys/bus/pci/devices/0000:$dev/power/control`)
- Created persistent udev rule `/etc/udev/rules.d/99-disable-chipset-aspm.rules` to apply both on every boot
- Affected devices: `04:00.0` (chipset PCIe switch), `0e:00.0` (xHCI USB), `10:00.0` (xHCI USB #2), `11:00.0` (AHCI SATA), `0c:00.0` (Atlantic NIC)

**Verified:** All chipset devices now show `LnkCtl: ASPM Disabled` and `power/runtime_status: active`.

**Rationale:** Every fatal lockup hits `pci_pm_runtime_resume` → `pci_mmcfg_read` spinning on a device in L1 that never wakes. Keeping links always active and devices never suspended removes both the L1 transition that may destabilize the fabric and the resume code path that causes the infinite spin.

**Status:** Monitoring. If the chipset still drops with ASPM and runtime PM disabled, the root cause is hardware (thermal/defective silicon) not power management.

## Recommended Next Steps

### Immediate — software mitigations

1. ~~**Disable PCIe runtime PM for chipset devices**~~ **Done** (2026-03-10). Applied live and persisted via udev rule. See intervention log above.

2. ~~**Disable ASPM on chipset devices**~~ **Done** (2026-03-10). `pcie_aspm=off` was already in cmdline but ineffective (BIOS overrides). Force-cleared via `setpci` and persisted via udev rule. See intervention log above.

### High priority — chipset-level investigation

3. **Check chipset heatsink and airflow** — the AMD 800 Series chipset handles SATA + USB + NIC + PCIe switching. If its heatsink has poor contact or no airflow, thermal runaway could cause the PCIe fabric to drop. Clean dust, verify heatsink is seated, consider adding a fan.

4. **Update BIOS** — currently BIOS 1512 (2025-06-05, AGESA 1.2.0.3e), 3 versions behind. Available: 1804 (AGESA 1.2.7.0, "improves compatibility with various CPUs and devices"), 2004 (AGESA Pre1.3.0.0, "enhanced stability"), 2102 beta (AGESA 1.3.0.0a, DDR5/boot fixes). No changelogs mention PCIe/SATA fixes explicitly (AMD doesn't publish detailed AGESA notes), but three major AGESA bumps likely include unadvertised chipset firmware fixes. Download from [ASUS support page](https://www.asus.com/us/motherboards-components/motherboards/proart/proart-x870e-creator-wifi/helpdesk_bios?model2Name=ProArt-X870E-CREATOR-WIFI). Note: BIOS file must be renamed with BIOSRenamer before USB flashback.

5. **Consider an HBA card** — a dedicated LSI/Broadcom HBA (e.g., 9300-8i in IT mode) would move SATA off the failing chipset entirely. Given the chipset-level PCIe failures, this may be the most practical workaround regardless of root cause.

6. **File an ASUS support ticket** — the pattern (SATA + USB + NIC all dying simultaneously behind the chipset PCIe switch) is distinctive. May be a known X870E issue or warrant an RMA.

### Lower priority

7. **Reseat remaining 2 bottom SATA cables** — unlikely to help given USB and NIC also fail, but eliminates the last cable variable.

8. **Check PSU voltages** — marginal 3.3V/5V could starve the chipset. Requires a multimeter on a SATA or Molex power connector — software cannot read PSU rails on this board. `lm-sensors` installed (2026-03-10); `asusec` ISA adapter exposes only temps (CPU, CPU Package, Motherboard, VRM, T_Sensor) and one fan (CPU_Opt). No `in*_input` voltage channels. Also check the 24-pin ATX connector for loose/corroded pins.

9. ~~**Run a ZFS scrub**~~ **Done** (2026-03-04). Completed with 0 errors. ZFS pools healthy after all powercycles.

### Monitoring

10. **Add chipset error monitoring** — a cron/systemd timer that watches `journalctl -k` for `ata.*SError|AHCI.*unavailable|soft lockup|xHCI.*not responding` and alerts (e.g., Healthchecks.io or webhook). Early detection won't prevent the hang but could enable a clean shutdown before cascade.

11. ~~**Set up smartd email alerts**~~ Partially done (2026-03-04) — `postfix`/`smartd` configured but **alerts are not reaching actual mailbox**. Needs mail delivery verification.
