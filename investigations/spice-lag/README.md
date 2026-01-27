# SPICE Lag Investigation

## Problem Statement

Using a desktop environment (GNOME) over SPICE on wyrm (VM) feels noticeably
laggy, even though atlas (Proxmox host) and wyrm are on the same physical
machine. However, vim running in a bare VT (not under X/Wayland) over SPICE
feels smooth and responsive.

## Setup Context

- **Atlas**: Proxmox host, AMD iGPU + two NVIDIA 5090s passed through to wyrm
- **wyrm**: VM 100, GPU passthrough (both 5090s), intended for compute
- SPICE connection is local (localhost, not routed through VPS)

### Current VM hardware config

From Proxmox (`/etc/pve/qemu-server/100.conf`):

- **Display**: QXL at PCI `00:01.0`
- **GPUs**: Two NVIDIA RTX 5090 (10de:2b85) passed through via VFIO at
  `01:00.0` and `02:00.0`
- **SPICE**: `spice_enhancements: videostreaming=all`
- **vga**: `qxl`

Note: `nvidia-smi` fails on wyrm — `/dev/nvidia*` devices are missing despite
PCI passthrough. The NVIDIA driver isn't loading. This is a separate issue from
SPICE lag but means the 5090s aren't usable for compute either.

### History: virtio-gpu to QXL switch

wyrm previously used `vga: virtio-gl` (VirGL). This broke ~3-4 weeks ago when
the two 5090s were added for GPU passthrough, and was switched to QXL as a
workaround. The ansible config (`ansible/inventory.yaml`) still has a comment
referencing the old `vga=virtio-gl` setting.

No journal evidence of the switch exists — `journalctl` on wyrm only goes back
to Jan 19, 2026 (journals rotated).

## Rendering Stack Explanation

### VT path (fast, ~58ms adjusted)

```
Keystroke → SPICE input channel → VM kernel → VT framebuffer console
→ QXL/SPICE grabs changed framebuffer region → SPICE image stream → client
```

The VT console writes directly to the framebuffer. QXL efficiently encodes
the small changed region (a few characters). No compositor, no OpenGL, no
video encoding overhead. ~58ms end-to-end (after subtracting ydotool overhead).

### GNOME/Wayland path (slow, ~107ms steady / ~422ms burst)

```
Keystroke → SPICE input channel → VM kernel → Wayland client (terminal)
→ Wayland compositor (GNOME Shell / Mutter)
→ OpenGL compositing via llvmpipe (CPU software rendering!)
→ Composited framebuffer → QXL driver
→ SPICE grabs changed region → video encoding (videostreaming=all)
→ SPICE video stream → client decodes
```

Every frame goes through:
1. **llvmpipe**: CPU-based OpenGL. Compositing the entire desktop in software
   is slow, especially under sustained updates.
2. **Video encoding**: `videostreaming=all` tells SPICE to encode
   frequently-changing regions as MJPEG/VP8 video. This adds encoding latency
   on top of the already-slow software rendering.
3. **Wayland compositor frame scheduling**: Mutter batches damage and
   composites on vsync boundaries, adding scheduling latency.

Under sustained typing, the pipeline can't keep up: frames queue, latency
balloons from ~107ms to 500-750ms, and eventually multiple keystrokes appear
in a single catch-up frame.

## Findings

### Latency measurements

Measured using `record.py` + `analyze.py` (see below). The approach: record the
host screen (which shows a millisecond clock alongside the SPICE window), type
single-character markers via ydotool, then use OpenAI vision API to read the
clock and vim buffer from each frame to determine when each marker first appears.

Markers are randomly shuffled non-confusable characters (not alphabetical) to
prevent vision model priming. Detection uses vim status bar column number
transitions (vim_col goes from N-1 to N), not character recognition.

#### 2026-01-27: VT over SPICE (baseline)

vim running in a bare VT (Ctrl+Alt+F1) on wyrm, no desktop compositor involved.

```
Samples: 10/10
Average: 98ms [91-106ms]
Min: 87ms, Max: 128ms
Frame interval: ±30.2ms (33.2 fps actual)
```

Adjusted for ~40ms ydotool overhead: **~58ms** actual SPICE latency.
Recording: `results/2026-01-27T04:19_baseline/`

#### 2026-01-27: GNOME desktop over SPICE (steady-state)

vim in terminal inside GNOME. One keystroke every 3 seconds.

```
Samples: 10/10
Average: 147ms [143-152ms]
Min: 120ms, Max: 159ms
Frame interval: ±29.7ms (33.6 fps actual)
```

Adjusted: **~107ms**. That's ~49ms more than VT.
Recording: `results/2026-01-27T04:41_gnome/`

#### 2026-01-27: GNOME burst typing (the real problem)

40 markers at 200ms intervals under GNOME/SPICE.

```
Samples: 40/40
Average: 462ms [458-465ms]
Min: -74ms, Max: 764ms
Frame interval: ±25.3ms (39.6 fps actual)
```

First 5 keystrokes land at ~160ms (matching steady-state), then latency jumps
to **500-750ms** as the pipeline saturates. Last markers drain the queue
(354ms, 140ms, then negative = catch-up frame with multiple characters).
Recording: `results/2026-01-27T04:51_gnome_burst/`

#### 2026-01-27: VT burst typing

40 markers at ~200ms intervals in a bare VT.

```
Samples: 37/40 (3 excluded: clock misreads)
Average: ~93ms [80-103ms]
Min: 80ms, Max: 103ms
Frame interval: ±27.9ms (35.8 fps actual)
```

Latency is flat across all 40 keystrokes — zero degradation under sustained
typing. Confirms the burst problem is desktop-specific, not SPICE transport.
Recording: `results/2026-01-27T06:17_vt_burst_clean/`

#### Comparison

| Setup                    | Raw avg | Adjusted | Notes                         |
| ------------------------ | ------- | -------- | ----------------------------- |
| VT over SPICE            | 98ms    | ~58ms    | Smooth, consistent            |
| VT burst                 | ~93ms   | ~53ms    | 40 markers, no degradation    |
| GNOME over SPICE (slow)  | 147ms   | ~107ms   | One keystroke every 3s        |
| GNOME over SPICE (burst) | 462ms   | ~422ms   | One keystroke every 200ms     |

### Ruled out: SPICE routing through VPS

`atlas.agentydragon.com` resolves to Atlas's Tailscale IP (100.64.1.30), and
all SPICE connections stay on localhost. VPS proxy is not involved.

## Known Issues (from research)

### SPICE + Wayland = deadly slow (confirmed by Proxmox staff)

Proxmox forum posts confirm GNOME on Wayland over SPICE is extremely slow.
Proxmox staff explicitly said "Gnome on Wayland? Deadly slow on spice" and
recommended switching to Xorg. This is likely the single biggest contributor
to our lag.

- https://forum.proxmox.com/threads/spice-performance-sluggish.85333/
- https://forum.manjaro.org/t/manjaro-gnome-vm-spice-wayland-performance-issues/99133
- https://forum.proxmox.com/threads/arch-linux-vm-spice-sluggish-performance.103092/

### videostreaming=all causes severe lag

Red Hat Bugzilla #1020393 and related reports document that
`spice_enhancements: videostreaming=all` causes severe lag, especially with
software rendering. The video encoding adds latency on every frame update.
With llvmpipe already struggling, the video encoder creates additional
backpressure.

- https://bugzilla.redhat.com/show_bug.cgi?id=1020393
- https://pve.proxmox.com/wiki/SPICE

### QXL + compositing = llvmpipe

QXL only provides 2D acceleration. Any 3D/compositing (which GNOME Shell
requires) falls back to llvmpipe (CPU software OpenGL). This is fundamental
to QXL and can't be fixed without switching display adapters.

- https://github.com/virt-manager/virt-manager/issues/752
- https://www.phoronix.com/forums/forum/linux-graphics-x-org-drivers/opengl-vulkan-mesa-gallium3d/998510-even-with-an-intel-core-i9-7980xe-llvmpipe-is-still-slow

## Bisection Plan

Each step should be tested independently with `record.py`/`analyze.py` burst
mode (40 markers, 200ms intervals). The GNOME burst test is the critical
benchmark — it's the one that shows the problem.

### Step 1: Switch GNOME to Xorg session (highest expected impact)

On the GDM login screen, select the gear icon and choose "GNOME on Xorg"
instead of "GNOME" (Wayland).

**Expected impact**: Large improvement. Wayland+SPICE is a known-bad combo.
Xorg GNOME still composites with llvmpipe but avoids Wayland-specific overhead.

**How to verify**: `echo $XDG_SESSION_TYPE` should show `x11` not `wayland`.

**Observation**: _(not yet tested)_

### Step 2: Disable videostreaming

In Proxmox web UI or `/etc/pve/qemu-server/100.conf`, change:
```
spice_enhancements: videostreaming=off
```
Or remove `spice_enhancements` entirely. Requires VM restart.

**Expected impact**: Moderate improvement. Removes MJPEG/VP8 encoding overhead
from every frame update. Most beneficial when combined with software rendering.

**Alternative**: `videostreaming=filter` — only encodes regions SPICE detects
as video content, not all screen updates.

**Observation**: _(not yet tested)_

### Step 3: Switch from QXL to virtio-gpu with VirGL

In Proxmox config, change `vga: qxl` to `vga: virtio-gl`. This enables VirGL,
which forwards OpenGL commands to the host GPU (AMD iGPU on atlas) for
hardware-accelerated compositing.

**Prerequisites** (check on atlas before attempting):
```bash
# Check render nodes exist (need /dev/dri/renderD128 or similar)
ls -la /dev/dri/

# Check amdgpu module is loaded
lsmod | grep amdgpu

# Check amdgpu is NOT blacklisted
grep -r amdgpu /etc/modprobe.d/

# Check EGL libraries are installed
dpkg -l | grep libegl

# Check virglrenderer is available
dpkg -l | grep virgl
```

**Expected impact**: Large improvement if it works. Compositing moves from
llvmpipe (CPU) to AMD iGPU (hardware). This is what wyrm used before the
5090s were added.

**Known risks**:
- Previously broke when 5090s were added — may need VFIO configuration that
  doesn't interfere with VirGL
- Need to ensure amdgpu driver is loaded for the iGPU while 5090s use vfio-pci
- Check `/etc/modprobe.d/` for blacklists that might block amdgpu
- virglrenderer needs to be installed on the host
- NVIDIA proprietary drivers on host don't support GBM, so VirGL must use
  the AMD iGPU, not the NVIDIA GPUs

**References**:
- https://forum.proxmox.com/threads/can-i-use-one-of-two-gpus-for-passthrough-and-the-other-for-virgl.141866/
- https://forum.proxmox.com/threads/difference-between-virtio-gpu-and-virgl-gpu.113619/
- https://forum.proxmox.com/threads/no-drm-render-node-detected-dev-dri-renderd-no-gpu-needed-for-virtio-gl-display.146092/
- https://www.collabora.com/news-and-blog/blog/2025/01/15/the-state-of-gfx-virtualization-using-virglrenderer/
- https://wiki.archlinux.org/title/QEMU/Guest_graphics_acceleration

**If it fails**: Check `journalctl -u qemu-server` and
`/var/log/pve/tasks/` on atlas. Also check the QEMU command line:
```bash
# On atlas:
ps aux | grep 'qemu.*100' | head -1
```
Look for `-display egl-headless,rendernode=/dev/dri/renderDN` in the args.

**Observation**: _(not yet tested)_

### Step 4: Try non-compositing WM (if VirGL unavailable)

If VirGL can't be made to work, try a window manager that doesn't require
OpenGL compositing:

- `sudo apt install xfce4` then select "Xfce Session" at login
- Or: `sudo apt install i3` for a tiling WM with zero compositing
- Or: disable GNOME compositing (unreliable, may break desktop)

**Expected impact**: Should match VT latency closely, since the rendering
path avoids OpenGL entirely.

**Observation**: _(not yet tested)_

### Step 5: Looking Glass or Sunshine/Moonlight (advanced)

Use one of the passed-through 5090s for display output, captured via shared
memory (Looking Glass) or network streaming (Sunshine/Moonlight).

- **Looking Glass**: Shared memory framebuffer, lowest possible latency,
  requires IVSHMEM setup and guest-side capture agent
- **Sunshine/Moonlight**: NVENC hardware encoding on the 5090, decoded on
  client. Requires NVIDIA driver working (currently broken — see above).

**Expected impact**: Potentially sub-16ms latency (Looking Glass) or
~30-50ms (Sunshine/Moonlight with hardware encode).

**Prerequisites**: NVIDIA driver must be loading (`nvidia-smi` currently
fails). Fix GPU passthrough first.

**References**:
- https://looking-glass.io/docs/B6/install/
- https://github.com/gnif/LookingGlass
- https://forum.proxmox.com/threads/trying-proxmox-with-sunshine.125200/
- https://forum.proxmox.com/threads/gpu-passthrough-with-nvidia-in-linux-vm-improve-stability.166766/

**Observation**: _(not yet tested)_

## Diagnostic Commands

### On wyrm (guest VM)

```bash
# Current display server
echo $XDG_SESSION_TYPE    # wayland or x11

# Current OpenGL renderer
glxinfo | grep renderer   # llvmpipe = software, virgl = hardware

# GPU devices visible
lspci | grep -i 'vga\|3d\|display'

# NVIDIA driver status
nvidia-smi                # currently fails
ls /dev/nvidia*           # currently empty
dmesg | grep -i nvidia    # check for driver load errors

# SPICE agent
systemctl status spice-vdagentd
```

### On atlas (Proxmox host)

```bash
# VM config
cat /etc/pve/qemu-server/100.conf

# QEMU command line (shows actual display backend)
ps aux | grep 'qemu.*100' | head -1

# Render nodes (needed for VirGL)
ls -la /dev/dri/

# GPU drivers loaded
lsmod | grep -E 'amdgpu|nvidia|vfio'

# Check for GPU blacklists
grep -r 'amdgpu\|nvidia\|nouveau' /etc/modprobe.d/

# VFIO bindings
ls -la /sys/bus/pci/drivers/vfio-pci/

# Proxmox QEMU logs
journalctl -u qemu-server --since today
ls /var/log/pve/tasks/

# virglrenderer availability
dpkg -l | grep virgl
apt list --installed 2>/dev/null | grep -i virgl
```

### Venus (Vulkan over virtio-gpu) — future option

Venus is virtio-gpu's Vulkan counterpart to VirGL's OpenGL. Not yet viable:

- Needs QEMU 9.2+ (check: `qemu-system-x86_64 --version`)
- Needs kernel 6.13+ on guest (check: `uname -r`)
- Needs `virgl-server` package on host
- Proxmox support is in-progress (patches under review)
- https://lore.proxmox.com/pve-devel/5595ba2c-b804-4b2c-bc5e-18c6141a9555@proxmox.com/T/
- https://docs.mesa3d.org/drivers/venus.html

## Measurement Tools

Two scripts in this directory:

### `record.py` — capture latency data

Records a screencast with an embedded millisecond clock while typing
randomly-shuffled non-confusable character markers into a focused SPICE/vim
window.

```bash
# On atlas (SPICE client machine):
cd investigations/spice-lag
python record.py --samples 10             # 10 markers, 3s apart (steady-state)
python record.py --samples 40 --delay 0.2 # 40 markers, 200ms apart (burst)
```

**Setup before recording:**

1. Open SPICE client to wyrm, position the window
2. In wyrm: `nvim --clean -c "set guicursor=a:blinkon0" -c "startinsert"`
3. Focus the SPICE window, then run record.py

**Output:** directory with `recording.webm`, `frames/`, `metadata.json`

**Note:** ydotool uses default 20ms hold + 20ms inter-key delays, adding ~40ms
to measured latency per character.

### `analyze.py` — compute latencies from recording

Reads a recording directory and computes input-to-display latency.

```bash
# Vision API analysis (recommended, more accurate):
python analyze.py <recording-dir> --vision

# Pixel-diff analysis (no API needed, less accurate):
python analyze.py <recording-dir>
```

Vision analysis uses OpenAI gpt-4o to read the clock time and vim status bar
column number from each frame. Marker detection uses vim_col transitions
(column goes from N to N+1), not character recognition — this is robust to
random/shuffled marker strings.

Results are cached in `~/.cache/spice-latency/vision/` (keyed by prompt hash
+ image content hash, so prompt changes invalidate cache automatically).

**Requirements:** direnv (`.envrc` creates venv with system-site-packages for
gi/PIL + installs openai)

## Priority-Ordered Action Items

1. **Switch to Xorg session** — Zero-cost change, largest expected single
   improvement. Just select "GNOME on Xorg" at GDM login.
2. **Disable videostreaming** — Set `videostreaming=off` in Proxmox config.
   Requires VM restart.
3. **Enable VirGL** — Switch `vga: virtio-gl`. Run host-side checks first
   (see diagnostic commands). Requires VM restart.
4. **Try non-compositing WM** — Install xfce4 or i3 as fallback if VirGL
   can't be made to work.
5. **Fix NVIDIA driver** — Separate from SPICE lag but needed for compute.
   Investigate why `/dev/nvidia*` is missing despite PCI passthrough.
6. **Sunshine/Moonlight** — Once NVIDIA driver works, this could replace
   SPICE entirely for desktop use.

## Session Notes

This investigation is running on wyrm itself. Config changes (display adapter,
SPICE settings, session type) require restarting the VM or at minimum logging
out, which means pausing/restarting the investigation session. The measurement
scripts run on atlas (the host), not wyrm.
