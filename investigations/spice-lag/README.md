# SPICE Lag Investigation

## Problem Statement

Using a desktop environment (GNOME) over SPICE on wyrm (VM) feels noticeably
laggy, even though atlas (Proxmox host) and wyrm are on the same physical
machine. However, vim running in a bare VT (not under X/Wayland) over SPICE
feels smooth and responsive.

## Setup Context

- **Atlas**: Proxmox host, AMD iGPU + two NVIDIA 5090s passed through to wyrm
- **wyrm**: VM with GPU passthrough (both 5090s), intended for compute
- SPICE connection is local (localhost, not routed through VPS)

## Findings

### Display stack

wyrm uses QXL as the SPICE display adapter. QXL accelerates 2D only — any
3D/compositing (GNOME Shell, Firefox, etc.) falls back to llvmpipe (CPU
software rendering):

```
$ glxinfo | grep renderer
OpenGL renderer string: llvmpipe (LLVM 15.0.7, 256 bits)
```

Additionally, `spice_enhancements: videostreaming=all` is set, encoding all
screen updates as video streams on top of the already-slow software rendering.

### Latency measurements

Measured using `record.py` + `analyze.py` (see below). The approach: record the
host screen (which shows a millisecond clock alongside the SPICE window), type
single-character markers via ydotool, then use OpenAI vision API to read the
clock and vim buffer from each frame to determine when each marker first appears.

#### 2026-01-27: VT over SPICE (baseline — the smooth case)

vim running in a bare VT (Ctrl+Alt+F1) on wyrm, no desktop compositor involved.

```
Samples: 10/10
Average: 98ms [91-106ms]
Min: 87ms, Max: 128ms
Frame interval: ±30.2ms (33.2 fps actual)
```

This includes ~40ms of ydotool overhead (20ms hold + 20ms inter-key delay),
so actual SPICE latency is estimated at **~58ms**. This feels smooth and
responsive in practice.

Recording: `results/2026-01-27T04:19_baseline/`

#### TODO: GNOME desktop over SPICE (the laggy case)

Same measurement setup, but vim running in a terminal inside the GNOME desktop
session on wyrm. This adds the Wayland/X compositor + llvmpipe rendering in the
path. Expected to be significantly slower.

### Ruled out: SPICE routing through VPS

`atlas.agentydragon.com` resolves to Atlas's Tailscale IP (100.64.1.30), and
all SPICE connections stay on localhost. VPS proxy is not involved.

## Measurement Tools

Two scripts in this directory:

### `record.py` — capture latency data

Records a screencast with an embedded millisecond clock while typing
single-character markers (a, b, c, ...) into a focused SPICE/vim window.

```bash
# On atlas (SPICE client machine):
cd investigations/spice-lag
python record.py --samples 10
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

Vision analysis uses OpenAI gpt-4o to read the clock time and vim buffer text
from each frame. Results are cached in `~/.cache/spice-latency/vision/`.

**Requirements:** direnv (`.envrc` creates venv with system-site-packages for
gi/PIL + installs openai)

## Potential Solutions

### Option 1: Switch to virtio-gpu with VirGL

Atlas has an AMD iGPU not passed through. Changing `vga: qxl` to `vga: virtio-gl`
would enable VirGL, forwarding OpenGL to the host iGPU for hardware-accelerated
compositing.

### Option 2: Disable desktop compositing

Use Xorg without compositing, or a lighter WM that doesn't need 3D.

### Option 3: Tune SPICE settings

Disable `spice_enhancements: videostreaming=all` to reduce encoding overhead.

### Option 4: Looking Glass

Use one NVIDIA for display via shared memory framebuffer capture. Low latency
but complex setup.

## Next Steps

1. Record GNOME-over-SPICE latency for comparison with VT baseline
2. Try solutions and re-measure to quantify improvement
