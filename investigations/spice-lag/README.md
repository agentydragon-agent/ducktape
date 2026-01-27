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

#### 2026-01-27: GNOME desktop over SPICE (the laggy case)

vim running in a terminal inside the GNOME desktop session on wyrm. This adds
the Wayland compositor + llvmpipe software rendering in the path.

```
Samples: 10/10
Average: 147ms [143-152ms]
Min: 120ms, Max: 159ms
Frame interval: ±29.7ms (33.6 fps actual)
```

Adjusted for ydotool overhead: **~107ms** actual latency. That's ~50ms more
than VT (58ms adjusted), attributable to the compositor + llvmpipe path.

Recording: `results/2026-01-27T04:41_gnome/`

#### 2026-01-27: GNOME burst typing (the real problem)

40 markers at 200ms intervals (burst typing) under GNOME/SPICE. This simulates
actual typing rather than isolated keystrokes with long pauses.

```
Samples: 40/40
Average: 462ms [458-465ms]
Min: -74ms, Max: 764ms
Frame interval: ±25.3ms (39.6 fps actual)
```

The first 5 keystrokes land at ~160ms (matching steady-state), then latency
jumps to **500-750ms** as something in the desktop rendering pipeline saturates.
The last few markers drain the queue (354ms, 140ms, then negative = multiple
characters rendered in a single catch-up frame).

Recording: `results/2026-01-27T04:51_gnome_burst/`

#### 2026-01-27: VT burst typing (partial — layout disrupted)

40 markers at ~200ms intervals in a bare VT over SPICE. The recording window
layout changed mid-recording (around marker v/w), causing a stall and
unreliable data in the second half.

```
Samples: 39/40
Average: 159ms [155-164ms]  (misleading — bimodal)
```

- **First half (a-v, 22 markers)**: ~91-121ms, consistent with VT steady-state
- **Layout disruption (w-z)**: Display stalled, 4 markers batched into 2 frames,
  producing negative/nonsensical values
- **Second half (A-N)**: ~254-322ms, consistently elevated

The first half confirms VT handles burst typing without degradation (~100ms,
same as steady-state). The second half is unreliable due to the mid-recording
layout change. A clean re-recording is needed.

Recording: `results/2026-01-27T04:55_vt_burst/`

#### Comparison

| Setup                    | Raw avg | Adjusted | Notes                      |
| ------------------------ | ------- | -------- | -------------------------- |
| VT over SPICE            | 98ms    | ~58ms    | Smooth, consistent         |
| VT burst (first half)    | ~100ms  | ~60ms    | 22 markers, no degradation |
| GNOME over SPICE (slow)  | 147ms   | ~107ms   | One keystroke every 3s     |
| GNOME over SPICE (burst) | 462ms   | ~422ms   | One keystroke every 200ms  |

The steady-state GNOME test (one key every 3 seconds) only adds ~49ms over VT.
But under sustained typing, the desktop pipeline can't keep up, causing
queueing and latency ballooning to 500-750ms.

VT burst typing (first 22 markers before recording disruption) shows no
degradation — latency stays at ~100ms, same as steady-state. This suggests the
sustained-typing problem is specific to the desktop path, not SPICE itself.
However, the VT burst recording was disrupted and needs a clean re-recording to
fully confirm this.

The bottleneck in the desktop path could be in:

- llvmpipe (software OpenGL compositing)
- SPICE video encoding (`videostreaming=all`)
- QXL driver overhead
- Wayland compositor frame scheduling
- Some combination of the above

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

1. Re-record VT burst without layout disruption for clean comparison
2. Try solutions and re-measure to quantify improvement
