# Atlas Black Screen Lockup — Recurring Chipset Failure

## Summary

Atlas (Proxmox host, ASUS ProArt X870E-CREATOR WIFI) has recurring system hangs (black screen, requires power-off) caused by the AMD 800 Series chipset PCIe fabric failing. The failure manifests as SATA link errors on the second AHCI controller (`ata7`–`ata10`), then escalates to the entire chipset subtree going offline — SATA, USB (xHCI), and Atlantic NIC all become inaccessible (`0xFFFFFFFF` reads), causing soft lockups and a hard hang.

Three incidents so far, every 1–2 days. SATA cable reseat on Mar 6 did **not** help — incident 3 occurred afterward with identical pattern plus USB controller death, confirming this is **not** a cable issue.

## Recurrence Log

| #   | Onset        | Hang          | Recovery                 | Uptime before failure | Devices affected                                    |
| --- | ------------ | ------------- | ------------------------ | --------------------- | --------------------------------------------------- |
| 1   | Feb 28 00:04 | Feb 28 ~18:05 | Mar 4 20:52 (powercycle) | ~5h after boot        | SATA (`ata7`, `ata8`, `ata10`)                      |
| 2   | Mar 5 02:38  | Mar 5 ~06:47  | Mar 6 01:17 (powercycle) | ~6h after boot        | SATA (`ata7`, `ata8`), Atlantic NIC, PCIe `08:08.0` |
| 3   | Mar 7 00:01  | Mar 7 ~06:42  | Mar 7 06:54 (powercycle) | ~23h after boot       | SATA (all 4), xHCI USB, Atlantic NIC                |

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

## PCIe Topology of Affected Devices

All affected devices share the same root port `0000:02.1` through the AMD 800 Series chipset PCIe switch:

```
0000:02.1 (CPU PCIe root port)
  └─ 04:00.0 (PCIe switch upstream)
      └─ 05:xx (switch downstream ports)
          ├─ 08:xx (inner PCIe switch)
          │   ├─ 0a: MediaTek WiFi
          │   ├─ 0b: Intel I226-V (igc) — not affected (yet)
          │   ├─ 0c: Aquantia Atlantic NIC — STUCK in incident 2, 3
          │   ├─ 0d: (empty downstream port) — FFFFFFFF in incident 2
          │   ├─ 0e: AMD xHCI USB — DEAD in incident 3
          │   └─ 0f: AMD SATA Controller #1
          ├─ 10: AMD xHCI USB #2
          └─ 11: AMD SATA Controller #2 — ata7-ata10, UNAVAILABLE in all incidents
```

## Analysis

- **Confirmed chipset-level failure**: Three different device types (SATA, USB, NIC) behind the same AMD 800 Series chipset PCIe hierarchy all fail simultaneously. This rules out SATA cables as the root cause.
- **Same escalation pattern**: `ata7` link errors → hard resets → AHCI controller unavailable → PCIe fabric returns `0xFFFFFFFF` → soft lockups → system hang
- **`ata7` is always the canary**: first to show errors in all 3 incidents, hours before the cascade
- **PCI config space `0xFFFFFFFF`** across multiple devices confirms the chipset's PCIe switch or its upstream link is dropping
- **Runtime PM is the trigger for the lockup**: the soft lockup always occurs in `pci_pm_runtime_resume` → `pci_mmcfg_read`, trying to restore a device that has already fallen off the bus. The kernel spins forever waiting for a response that will never come
- **Atlantic NIC has independent flakiness** (link flap at Mar 6 01:52 with no other symptoms), but its MMIO hangs during the lockup events are caused by the shared chipset failure, not the NIC itself
- SMART health: all 4 drives PASSED, zero reallocated/pending/uncorrectable sectors
- ZFS pools: ONLINE with zero errors after every powercycle

**Conclusion**: The AMD 800 Series chipset (Promontory successor) on this ASUS ProArt X870E-CREATOR WIFI has a recurring failure where its internal PCIe fabric drops out, taking all downstream devices offline. Possible causes: chipset thermal issue, chipset firmware bug, defective chipset, or marginal power delivery to the chipset.

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

## Recommended Next Steps

### High priority — chipset-level investigation

1. **Check chipset heatsink and airflow** — the AMD 800 Series chipset handles SATA + USB + NIC + PCIe switching. If its heatsink has poor contact or no airflow, thermal runaway could cause the PCIe fabric to drop. Clean dust, verify heatsink is seated, consider adding a fan.

2. **Check BIOS version** — currently BIOS 1512 (2025-06-05). Check ASUS for a newer X870E-CREATOR WIFI BIOS addressing PCIe/SATA stability. AMD chipset firmware bugs have caused similar issues historically.

3. **Consider an HBA card** — a dedicated LSI/Broadcom HBA (e.g., 9300-8i in IT mode) would move SATA off the failing chipset entirely. Given the chipset-level PCIe failures, this may be the most practical workaround regardless of root cause.

4. **File an ASUS support ticket** — the pattern (SATA + USB + NIC all dying simultaneously behind the chipset PCIe switch) is distinctive. May be a known X870E issue or warrant an RMA.

### Lower priority

5. **Reseat remaining 2 bottom SATA cables** — unlikely to help given USB and NIC also fail, but eliminates the last cable variable.

6. **Check PSU voltages** — marginal 3.3V/5V could starve the chipset. A multimeter on a SATA power connector would confirm. Also check the 24-pin ATX connector for loose/corroded pins.

7. ~~**Run a ZFS scrub**~~ **Done** (2026-03-04). Completed with 0 errors. ZFS pools healthy after all 3 powercycles.

### Monitoring

8. **Add chipset error monitoring** — a cron/systemd timer that watches `journalctl -k` for `ata.*SError|AHCI.*unavailable|soft lockup|xHCI.*not responding` and alerts (e.g., Healthchecks.io or webhook). Early detection won't prevent the hang but could enable a clean shutdown before cascade.

9. ~~**Set up smartd email alerts**~~ Partially done (2026-03-04) — `postfix`/`smartd` configured but **alerts are not reaching actual mailbox**. Needs mail delivery verification.
