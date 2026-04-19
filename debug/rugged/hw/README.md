# Dell Pro Rugged 12 Tablet (RA02260) — Hardware Hub

**Last updated**: 2026-04-18
**Kernel**: 6.19.7 | **linux-firmware**: 20260309 | **Platform**: NixOS, Intel Lunar Lake
**NixOS config**: <nix/nixos/hosts/rugged/default.nix>

## Hardware Inventory

| Component      | Device                        | PCI/USB ID  | Driver                 | Status          | Notes                 |
| -------------- | ----------------------------- | ----------- | ---------------------- | --------------- | --------------------- |
| CPU            | Intel Core Ultra (Lunar Lake) | —           | —                      | Working         |                       |
| GPU            | Intel Arc 130V/140V           | `8086:64a0` | `xe`                   | Working         | Vulkan crash (GTK4)   |
| Wi-Fi          | Intel Wi-Fi 7 BE201 320MHz    | `8086:a840` | `iwlwifi`/`iwlmld`     | Working         | Cosmetic WEXT warn    |
| Bluetooth      | Intel BE201 (PCIe)            | `8086:a876` | `btintel_pcie`         | **Broken**      | [details](#bluetooth) |
| Webcam         | OmniVision OV08F40 via IPU7   | `8086:645d` | `intel_ipu7` (staging) | **Partial**     | [details](#webcam)    |
| NPU            | Intel Lunar Lake NPU          | `8086:643e` | `intel_vpu`            | **Needs setup** | [details](#npu)       |
| Audio          | Realtek ALC3204 (HDA)         | `8086:a828` | `snd_hda_intel`        | Working         |                       |
| NVMe           | KIOXIA EG6 (DRAM-less)        | `1e0f:001b` | `nvme`                 | Working         |                       |
| Touchscreen    | eGalax EETI8082 (I2C)         | `0EEF:C005` | `hid-multitouch`       | Working         | + stylus              |
| SD Card Reader | Realtek RTS525A               | `10ec:525a` | `rtsx_pci`             | Working         |                       |
| 5G Modem       | Foxconn DW5934e (SDX72)       | `105b:e11d` | `mhi_pci_generic`      | **Partial**     | [details](#5g-modem)  |
| Fingerprint    | Broadcom BCM 58200            | `0a5c:5867` | none                   | **No driver**   |                       |
| Sensor Hub     | Intel ISH (3 sensors)         | —           | `intel_ish_ipc`        | Working         | Cosmetic warn         |
| Thunderbolt 4  | Intel Lunar Lake-M            | `8086:a831` | `xhci_hcd`             | Working         |                       |

## Priority Issues

### Webcam

**Goal**: Painless Zoom / Chrome / browser video calls.

**Working path**: libcamera + SoftISP + PipeWire camera portal.

- NixOS module: <nix/nixos/modules/ipu7-camera.nix> (enabled)
- `snapshot` works (with `GSK_RENDERER=gl`).
- PipeWire camera portal (`org.freedesktop.portal.Camera`) is active and
  `IsCameraPresent=true`. WirePlumber exposes PipeWire node 97 ("Built-in Front
  Camera") via `api.libcamera.source`.
- **Chrome 147 works** with: `NIXOS_OZONE_WL=1` (native Wayland, not XWayland)
  - `--enable-features=WebRtcPipeWireCamera`. Without these, Chrome falls back to
    raw V4L2 `/dev/video*` nodes which are non-functional (IPU7 needs libcamera ISP).
    The feature flag is `WebRtcPipeWireCamera` (not `PipeWireCamera`).
- Known issue: green tint from uncalibrated sensor. Needs color correction matrix
  in `/usr/share/libcamera/ipa/simple/uncalibrated.yaml`.
- **Zoom 6.6**: uses raw V4L2 only for camera (PipeWire support is screen-sharing only).
  Shows "ipu7" (raw V4L2 node), all black. Confirmed by `strings` on binary: camera uses
  `/dev/video%u`, no `AccessCamera` portal calls in Zoom's own code (only in embedded
  Chromium `libcef.so`). No indication Zoom is working on PipeWire camera support.

**Next steps**:

- Make Chrome config permanent: set `NIXOS_OZONE_WL=1` in
  `environment.sessionVariables` and add `WebRtcPipeWireCamera` to Chrome flags
- Test if green tint fix resolves color issues

**v4l2loopback recipe for Zoom** (not deployed, use if Zoom camera is needed later):

Add to `ipu7-camera.nix`:

```nix
# v4l2loopback kernel module
boot.extraModulePackages = [ config.boot.kernelPackages.v4l2loopback ];
boot.kernelModules = [ "v4l2loopback" ];
boot.extraModprobeConfig = ''
  options v4l2loopback video_nr=99 card_label="IPU7 Camera" exclusive_caps=1
'';

# GStreamer for the bridge pipeline
environment.systemPackages = with pkgs; [
  gst_all_1.gstreamer
  gst_all_1.gst-plugins-base
  gst_all_1.gst-plugins-good
];
```

Then bridge PipeWire camera → loopback (run before starting Zoom):

```bash
# Find the libcamera PipeWire node ID (look for media.role = "Camera")
NODE=$(pw-cli list-objects | grep -B5 'media.role = "Camera"' | grep 'id ' | awk '{print $2}' | tr -d ',')

# Set GStreamer plugin path (NixOS — adjust store paths)
export GST_PLUGIN_PATH="$(nix-build '<nixpkgs>' -A pipewire --no-out-link)/lib/gstreamer-1.0:$(nix-build '<nixpkgs>' -A gst_all_1.gst-plugins-good --no-out-link)/lib/gstreamer-1.0:$(nix-build '<nixpkgs>' -A gst_all_1.gst-plugins-base --no-out-link)/lib/gstreamer-1.0:$(nix-build '<nixpkgs>' -A gst_all_1.gstreamer --no-out-link)/lib/gstreamer-1.0"

# Bridge: PipeWire camera → v4l2loopback
gst-launch-1.0 -e pipewiresrc path=$NODE ! videoconvert ! \
  video/x-raw,format=YUY2,width=1280,height=720,framerate=30/1 ! \
  v4l2sink device=/dev/video99
```

Can also be wired as a systemd user service (see git history for a prior version).

**Vulkan crash**: GTK4 apps (including `snapshot`) segfault with `VK_ERROR_DEVICE_LOST`
on Lunar Lake. Workaround: `GSK_RENDERER=gl`. TODO in `default.nix` to add to
`environment.sessionVariables`.

---

### 5G Modem

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

---

### Bluetooth

**Status**: Broken. `btintel_pcie 0000:00:14.7: probe with driver btintel_pcie failed with error -62`

**Device**: Intel BE201 PCIe (`8086:a876`, subsystem `8086:000e`), driver `btintel_pcie`.

**What we know**:

- Error -62 is `ETIME` (not `ETIMEDOUT`/-110). In the driver source, this comes from
  `btintel_pcie_enable_bt()`: the driver sets `MAC_INIT` on the controller and waits
  3000ms for a GP0 "alive" MSI-X interrupt. That interrupt never fires.
- **The failure is pre-firmware.** The device never boots to ROM stage, so firmware
  name construction (from TLV data) never happens. The `ibt-*-pci.{sfi,ddc}` files
  on disk are not relevant to this failure.
- After probe failure: PCI device `enable=0`, `BusMaster-`, no driver bound.
- `rfkill list` shows only `phy0: Wireless LAN` — Bluetooth is not listed at all,
  meaning rfkill never gets a chance to register it (probe fails before that).
- Wi-Fi (`00:14.3`, same CNVi silicon) works fine. The BT function is independently
  gated.
- All known kernel fixes (6.13 recovery mechanism, handshake sync, DSBR) are present
  in 6.19. No new `btintel_pcie` patches in kernel 7.0.
- The driver has zero module parameters — no way to increase timeout without patching.
- No physical wireless kill switch on this tablet (confirmed via Dell documentation).
  The Pro Rugged 12 has programmable buttons (P1/P2/P3) but no hardware radio slider.

**Possible causes** (not yet confirmed):

1. **BIOS has Bluetooth disabled** — Dell Rugged BIOS has independent WLAN and
   Bluetooth toggles under the Connection/Wireless menu. If BT is disabled, the
   PCI function may be powered down and unable to fire the GP0 interrupt.
2. **MSI-X delivery failure** — the interrupt vector is allocated but the platform
   isn't routing it (ACPI/IOMMU issue).
3. **Device stuck in bad power state** — the BT function never completes power-on.
4. **Firmware on the device itself is bad** — the BT controller's onboard ROM is
   corrupt or incompatible (would require fwupd/Dell firmware update).

**Diagnostic steps** (in order):

1. **Check BIOS**: Reboot → hold Volume Down (or F2 with keyboard) → look under
   "Connection" or "Wireless" for an independent Bluetooth enable/disable toggle.
   Enable it if disabled.

2. **After BIOS check, re-probe the driver**:

   ```bash
   # Remove and rescan PCI device to re-trigger probe
   sudo sh -c 'echo 1 > /sys/bus/pci/devices/0000:00:14.7/remove'
   sudo sh -c 'echo 1 > /sys/bus/pci/rescan'
   dmesg | tail -20
   ```

3. **Check MSI-X state** (requires root):

   ```bash
   sudo lspci -vvv -s 00:14.7 | grep -A5 'MSI-X\|Capabilities'
   cat /proc/interrupts | grep btintel
   ```

   If interrupt count is 0 after a probe attempt, MSI-X is not being delivered.

4. **Enable dynamic debug** (if available) for verbose probe logging:

   ```bash
   sudo sh -c 'echo "module btintel_pcie +p" > /sys/kernel/debug/dynamic_debug/control'
   sudo sh -c 'echo "module btintel +p" > /sys/kernel/debug/dynamic_debug/control'
   # Then re-probe as above
   ```

5. **Check Dell firmware updates**:

   ```bash
   fwupdmgr get-devices | grep -A5 -i bluetooth
   fwupdmgr update
   ```

6. **If all else fails** — build kernel with increased timeout
   (`BTINTEL_DEFAULT_INTR_TIMEOUT_MS` in `drivers/bluetooth/btintel_pcie.h`,
   default 3000ms → try 15000ms) to rule out a slow-boot scenario. Or file
   upstream bug with full `lspci -vvv` output for the device.

**References**:

- [btintel_pcie.c probe flow](https://github.com/torvalds/linux/blob/v6.14/drivers/bluetooth/btintel_pcie.c) — `btintel_pcie_enable_bt()` is the failing function
- [Ubuntu Bug #2085485](https://bugs.launchpad.net/ubuntu/+source/linux/+bug/2085485)
- [Dell Pro Rugged 12 Service Manual — BIOS](https://www.dell.com/support/manuals/en-us/dell-pro-ra02260-rugged-tablet/dell-pro-ruggedtab-12_ra02260_sm_a00/entering-bios-setup-program)

---

### NPU

**Goal**: Local AI inference (small LLMs, vision tasks).

**Current state**: Kernel driver works, `/dev/accel/accel0` exists, firmware loaded.
NixOS userspace driver enabled (`hardware.cpu.intel.npu.enable = true` in `default.nix`).

**Smoke test**:

```bash
npu-umd-test  # bundled validation suite
```

**LLM inference on NPU**:

Ollama has no NPU support (open issues
[#8281](https://github.com/ollama/ollama/issues/8281),
[#5747](https://github.com/ollama/ollama/issues/5747)).

**NPU inference frameworks** (ranked by maturity):

| Framework              | Maturity    | Model limit | NixOS path               |
| ---------------------- | ----------- | ----------- | ------------------------ |
| **OpenVINO GenAI**     | Best        | ~7-8B int4  | pip venv + kernel module |
| **ipex-llm**           | Moderate    | ~7B int4    | Container likely needed  |
| **llama.cpp OpenVINO** | Low for NPU | ~3B         | Manual OpenVINO install  |
| **NPU Accel Library**  | Stale       | ~7B         | Not recommended          |

1. **OpenVINO GenAI** (`openvino-genai` pip package) — most mature path. Export model
   to OpenVINO IR format via `optimum-intel`, run with `device="NPU"`. Supports Llama
   2/3, Phi-2/3, Qwen 2, Gemma 2B with int4 quantization. On NixOS: install via pip
   in a venv, ensure `intel_vpu` kernel module is loaded.

2. **ipex-llm** — Intel's library has experimental NPU support for Lunar Lake. Uses
   OpenVINO internally. On NixOS: container likely needed due to complex deps
   (oneAPI, OpenVINO, specific PyTorch versions).

3. **llama.cpp + OpenVINO backend** (`-DGGML_OPENVINO=ON`,
   `GGML_OPENVINO_DEVICE=NPU`) — merged upstream April 2026. Best for small models
   (1-3B params), small context (`-c 512`). Validated: Llama-3.2-1B, Phi-3-mini,
   Qwen2.5-1.5B. Supported quantizations: FP16, Q8_0, Q4_0, Q4_1, Q4_K, Q4_K_M.

4. **Intel NPU Acceleration Library** — research/demo project, sparse commits, not
   recommended.

**Lunar Lake NPU has ~45 TOPS int8** — useful for background/offline inference on small
models, not as a primary inference accelerator.

**NixOS blocker**: OpenVINO GenAI needs OpenVINO 2024.0+. nixpkgs has 2025.2.1 (library
only, no CLI tools). The llama.cpp backend needs OpenVINO 2026.x (not yet in nixpkgs).
Practical path: pip venv for OpenVINO GenAI, or wait for nixpkgs bumps.

**Known issue**: [nixpkgs#470638](https://github.com/NixOS/nixpkgs/issues/470638) —
`hardware.cpu.intel.npu.enable` may not be available depending on nixpkgs pin. If so,
add manually:

```nix
hardware.firmware = [ pkgs.intel-npu-driver.firmware ];
hardware.graphics.extraPackages = [ pkgs.intel-npu-driver ];
environment.systemPackages = [ pkgs.level-zero pkgs.intel-npu-driver.validation ];
```

---

### Local LLM Inference (Arc GPU + NPU)

**Goal**: Run small LLMs locally for offline/low-latency use (shell helpers, editor
completions, summarization). Separate from cluster ollama at `ollama.allegedly.works`.

**Hardware**: Arc 130V/140V iGPU (SYCL), Lunar Lake NPU (OpenVINO). 30GB RAM.

#### Arc GPU path (SYCL) — running

IPEX-LLM Docker container (`intelanalytics/ipex-llm-inference-cpp-xpu`) runs as
`podman-ipex-ollama.service` via `virtualisation.oci-containers`. NixOS modules:
<nix/nixos/modules/local-llm-arc.nix>, <nix/nixos/modules/local-llm-npu.nix>.

- API at `http://localhost:11434` (OpenAI-compatible)
- Model storage: `/var/lib/local-llm/ollama`
- Qwen3 4B (Q4_K_M) installed, **26 tok/s on CPU** (2026-04-18)

```bash
# Pull models:
sudo podman exec ipex-ollama /llm/ollama/ollama pull qwen3:4b
# Test:
curl http://localhost:11434/api/generate -d '{"model":"qwen3:4b","prompt":"Hello","stream":false}'
```

**TODO**: Ollama reports `library=cpu` — model runs on CPU, not Arc GPU. Need to
investigate whether SYCL GPU offload is working. Check `sycl-ls` inside container
and whether `/dev/dri` is visible. May need `--group-add render` or driver mismatch
between host and container.

**TODO**: `npu-llm setup` pip installs CUDA torch (~1.5GB wasted). Use
`--index-url https://download.pytorch.org/whl/cpu` for CPU-only torch.

**NixOS native ollama blockers** (why container is needed):

- `services.ollama.acceleration` only supports `"cuda"` and `"rocm"` — no `"intel"`
  option ([nixpkgs#327999](https://github.com/NixOS/nixpkgs/issues/327999))
- Intel DPC++/SYCL compiler not in nixpkgs
  ([nixpkgs#367722](https://github.com/NixOS/nixpkgs/issues/367722))

**Good model candidates** for 30GB RAM + Arc 130V:

- Qwen3 4B — strong general reasoning, tool-calling
- Gemma 3 4B — good instruction following
- Phi-4 Mini 3.8B — code/math
- Qwen2.5-Coder 7B — code completion

#### NPU path — venv being set up

NixOS module: <nix/nixos/modules/local-llm-npu.nix>. Uses pip venv with
`optimum-intel` (not in nixpkgs). Model storage: `/var/lib/local-llm/openvino`.

```bash
npu-llm setup                                # one-time: create pip venv
npu-llm export Qwen/Qwen2.5-1.5B-Instruct    # export model to OpenVINO IR
npu-llm chat Qwen/Qwen2.5-1.5B-Instruct      # interactive chat on NPU
npu-llm server Qwen/Qwen2.5-1.5B-Instruct    # API on :11435
```

---

## Working Hardware (no action needed)

| Component                        | Notes                                                                                                    |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **GPU** (`xe`)                   | DMC v2.29, GuC v70.58.0, HuC v9.4.13, GSC v104.0.5.1429. Cosmetic "selective fetch" msg.                 |
| **Wi-Fi 7** (`iwlwifi`/`iwlmld`) | FW v101. WEXT warning is from userspace apps, harmless.                                                  |
| **Audio** (ALC3204)              | Speaker, headphone, internal+headset mic. SOF modules loaded.                                            |
| **Touchscreen** (EETI8082)       | Multitouch + stylus. I2C HID.                                                                            |
| **NVMe** (KIOXIA EG6)            | Working.                                                                                                 |
| **SD Card Reader** (RTS525A)     | Working.                                                                                                 |
| **Sensor Hub** (ISH)             | 3 sensors. Cosmetic `hid_field_extract` warn (rate-limited). IIO sensor proxy enabled for auto-rotation. |
| **Thunderbolt 4**                | USB4, two root ports.                                                                                    |

## Unsupported Hardware

| Component                              | Notes                                                                                                                                                                                        |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fingerprint** (Broadcom `0a5c:5867`) | No open-source driver. Proprietary `libfprint-2-tod1-broadcom` TOD plugin may work for similar IDs (`0a5c:5843`/`5842`) but unlikely for `5867`. Dell does not support fingerprint on Linux. |

## Related Files

- <esim.md> — 5G modem eSIM provisioning, FCC unlock research, lpac commands
- <nix/nixos/hosts/rugged/default.nix> — NixOS system configuration
- <nix/nixos/modules/ipu7-camera.nix> — IPU7 webcam NixOS module
