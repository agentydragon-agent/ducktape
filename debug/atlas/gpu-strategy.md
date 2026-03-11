# Atlas GPU Strategy

## Goal

Use 2x RTX 5090 GPUs flexibly:

- **Default**: Available to k8s cluster (Ollama, ML workloads)
- **On demand**: Switch one or both to a Windows/gaming VM without rebooting atlas

## Hardware

- **Motherboard**: ASUS ProArt X870E-CREATOR WIFI (Rev 1.xx)
- **CPU**: AMD Ryzen 9 9950X3D (16-core)
- **RAM**: 128 GB (structurally tight — wyrm2 alone takes 112 GB)
- **GPUs**: 2x NVIDIA RTX 5090 (GB202, Blackwell)
  - GPU 0: `01:00.0` → IOMMU group 14 (VGA + audio, clean)
  - GPU 1: `03:00.0` → IOMMU group 16 (VGA + audio, clean)
- **BIOS**: AMI v1512 (2025-06-05)
- **Kernel cmdline**: `amd_iommu=on iommu=pt pcie_aspm=off`

## Current State (Mar 2026)

- **GPUs idle** — no passthrough, no host driver, nobody using them
- **VM autostart disabled** after VFIO crashes
- **ASPM L1 and PCIe runtime PM disabled** via udev rules (mitigates chipset hangs)
- **IOMMU passthrough mode fix applied** (was missing due to systemd-boot
  misconfiguration — Ansible wrote to grub instead of `/etc/kernel/cmdline`)

## Known Problems

### 1. Chipset PCIe fabric instability (incidents 1–6)

Slow-onset: SATA errors start ~5-6h after boot, escalate to full chipset dropout
(SATA + USB + NIC all on same root port `0000:02.1`). Soft lockups in
`pci_pm_runtime_resume` → `pci_mmcfg_read` returning `0xFFFFFFFF`.

**Trigger**: ASPM L1 power state transitions.
**Mitigation**: Disabled ASPM L1 + runtime PM. System stable without VMs since.
**Root cause**: Unknown — firmware, thermal, or silicon defect.

### 2. VFIO GPU reset crashes (incidents 7–10)

System freezes within 30–60 seconds of boot when VFIO resets 2x RTX 5090 for
wyrm2 VM. Same chipset PCIe fabric failure pattern. VFIO reset generates heavy
PCIe traffic that destabilizes the chipset.

### 3. Blackwell VFIO is bleeding edge

RTX 5090 + open kernel module + VFIO is very new. Proprietary driver may be
more stable but hasn't been tested. Driver 580.x VFIO support may have bugs.

## What We Don't Know

- [ ] Can NVIDIA drivers load on the Proxmox host? (`nvidia-smi` from host)
- [ ] Does VFIO with only 1 GPU also crash? (never tested)
- [ ] Is there a BIOS update? (current is v1512, could be behind)
- [ ] Does the IOMMU passthrough fix (was missing before) change VFIO stability?
- [ ] Would proprietary NVIDIA driver help VFIO stability?
- [ ] Is it thermal? (chipset heatsink condition unknown)
- [ ] Would a PCIe HBA card for SATA reduce root-port contention?

## Options

### Option A: Host-native GPU + LXC bind-mount (no VFIO for k8s)

Load NVIDIA drivers on atlas host. Expose GPUs to k8s via the lxc-k8s-test
container with `/dev/nvidia*` bind-mounts. For gaming, stop the container,
unload host driver, VFIO-bind one GPU, start a Windows VM.

**Pros**:

- No VFIO for the common case — avoids the crash trigger entirely
- LXC GPU access is well-supported (bind-mount, no reset needed)
- Host `nvidia-smi` gives direct visibility

**Cons**:

- Gaming still needs VFIO (may still crash)
- Driver unload → VFIO rebind → VM start is multi-step
- Host NVIDIA driver + Proxmox may have quirks
- No GUI from LXC (headless only, but k8s workloads are headless anyway)

### Option B: VFIO to a single lightweight VM

Pass only 1 GPU via VFIO to a small NixOS VM (k8s worker). Other GPU idle
or host-native.

**Pros**: Reduces VFIO surface (1 GPU may not trigger the crash).
**Cons**: Still uses VFIO. Only 1 GPU for k8s. Untested whether 1 GPU is stable.

### Option C: Debug VFIO first, then decide

1. Update BIOS
2. Reboot with the IOMMU passthrough fix (already applied, not yet rebooted?)
3. Test VFIO with 1 GPU only
4. Try proprietary NVIDIA driver
5. Check chipset thermals
6. If all fails, RMA motherboard

**Pros**: May unlock the original plan.
**Cons**: Could be a long rabbit hole.

### Option D: Bare-metal Linux, no Proxmox

Ditch Proxmox. Run NixOS directly on hardware. k8s worker + desktop on same
machine. Windows gaming via dual-boot or GPU-passthrough with libvirt/QEMU.

**Pros**: No hypervisor overhead. Direct GPU access. Simplest for daily use.
**Cons**: Loses Proxmox VM management. Can't run Windows VM alongside Linux
without VFIO (which may still crash). Dual-boot means rebooting for Windows.

## Recommended Path

**Start with Option A** (host-native GPU, lowest risk), but first:

1. **Reboot atlas** to pick up the IOMMU passthrough fix
2. **Install NVIDIA drivers on the host** and test `nvidia-smi`
3. **Set up LXC GPU bind-mount** (per `TODO.md` plan)
4. **Verify k8s can use GPUs via LXC**

If host-native works, we have a stable k8s GPU path. Gaming can be tackled
separately (Option C debugging) without blocking the primary use case.

## Related Debug Files

- <black_screen_lockup.md> — chipset PCIe fabric instability (incidents 1–10)
- <locked-gpus/NOTES.md> — VFIO IOMMU misconfiguration discovery + fix
- <wyrm_gpu_lockup.md> — GPU lockwatch timeouts under VFIO
- <ethernet_recurring/README.md> — network drops (cable issue, separate)
