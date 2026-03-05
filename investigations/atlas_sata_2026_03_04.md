# Atlas SATA Link Failure — Recurring

## Summary

Atlas (Proxmox host, ASUS ProArt X870E-CREATOR WIFI) has recurring SATA link failures on the second AHCI controller (`ata7`–`ata10`) that escalate to full system hangs. Two incidents so far, ~5 days apart. SATA cables have **not yet been reseated**.

## Recurrence Log

| #   | Onset        | Hang          | Recovery                 | Uptime before failure | Drives affected         |
| --- | ------------ | ------------- | ------------------------ | --------------------- | ----------------------- |
| 1   | Feb 28 00:04 | Feb 28 ~18:05 | Mar 4 20:52 (powercycle) | ~5h after boot        | `ata7`, `ata8`, `ata10` |
| 2   | Mar 5 02:38  | Mar 5 ~06:47  | Pending                  | ~6h after boot        | `ata7`, `ata8`          |

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

## Analysis

- **Same controller, same pattern**: `ata7` always fails first, `ata8` follows. Same SATA link-layer error flags
- **Escalation path**: link errors → hard resets → interface fatal error → PCI device goes offline → soft lockup → hang
- SMART health: all 4 drives PASSED, zero reallocated/pending/uncorrectable sectors (as of incident 1)
- The PCI config space returning `0xFFFFFFFF` in incident 2 suggests either the AHCI controller or the chipset's PCIe-to-SATA bridge is losing its mind — not just signal integrity on cables
- The Atlantic NIC going down simultaneously points toward a **chipset-level issue** (X870E uses AMD Promontory chipset for SATA/USB/NIC), not isolated SATA cabling. **Note**: the Atlantic NIC has a history of flakiness independent of SATA issues, so the simultaneous drop may be coincidence rather than proof of a shared root cause

**Conclusion**: Most likely a SATA controller or physical interconnect issue. The PCI-level failure and NIC drop in incident 2 _could_ indicate a chipset-level problem, but the Atlantic NIC's independent flakiness weakens that signal. Reseating SATA cables remains the top priority.

## Recommended Next Steps

### Immediate — do these now

1. **Reseat all SATA cables** on the second AHCI controller (`ata7`–`ata10`). **Not yet done** as of Mar 5. Check for bent pins, loose connectors, cables routed near heat sources. While the PCI-level failure suggests something deeper, this is zero-cost and eliminates the simplest hypothesis.

2. **Check PCIe slot seating** — if the Atlantic NIC or any SATA controller is on an add-in card or riser, reseat it. The PCIe device going inaccessible could be a loose card.

3. **Check chipset heatsink and airflow** — the X870E Promontory chipset handles SATA + USB + some PCIe lanes. If its heatsink has poor contact or no airflow, thermal throttling or brown-outs could cause exactly this cascade. Clean dust, verify heatsink is seated.

4. **Check BIOS version** — currently BIOS 1512 (2025-06-05). Check ASUS for a newer X870E-CREATOR WIFI BIOS addressing SATA or PCIe stability. AMD Promontory has had firmware-level bugs in the past.

### Monitoring

5. ~~**Set up smartd email alerts**~~ Partially done (2026-03-04) — `postfix`/`smartd` configured but **alerts are not reaching actual mailbox**. Needs mail delivery verification (check `postfix` relay config, test with `echo test | mail -s test user@domain`).

6. **Add SATA error monitoring** — a cron job or script that watches `journalctl -k` for `ata.*SError` and alerts (e.g., via Healthchecks.io or a webhook). Catching link errors early before they cascade to a hang.

7. ~~**Run a ZFS scrub**~~ **Started** (2026-03-04). Check result with `zpool status tank` after next boot.

### If it recurs after reseating

8. **Swap SATA cables** between the two controllers (move a `tank` drive to `ata1`–`ata4` ports) to isolate controller vs cables.

9. **Try `pcie_aspm=off` for the SATA controller** — already set globally in kernel cmdline, but verify it's taking effect. ASPM power management on marginal links can trigger exactly these symptoms.

10. **Consider an HBA card** — a dedicated LSI/Broadcom HBA (e.g., 9300-8i in IT mode) bypasses the Promontory SATA controller entirely. Given the PCI-level failures, this may be necessary regardless of cable state.

11. **File an ASUS support ticket** with the journal excerpts — this pattern (SATA + PCIe NIC dropping off bus simultaneously) may be a known X870E issue.

12. **Check PSU voltages** — marginal 5V or 3.3V can cause SATA link instability. A multimeter on a SATA power connector would confirm.
