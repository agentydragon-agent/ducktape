# SPICE Audio Choppiness Investigation

## Problem

Audio over SPICE on wyrm2 has slight choppiness (~1 glitch every 10-60s).
`pw-top` shows xruns (ERR column) accumulating on the ALSA sink.

## Setup

- VM: wyrm2 (Proxmox q35, NixOS, GNOME 49 Wayland)
- Audio device: `ich9-intel-hda` with SPICE driver
- Audio stack: PipeWire 1.4.9 + pipewire-pulse + WirePlumber
- Note: Two HDA cards present — card 0 is the q35 chipset built-in (no codecs, unused),
  card 1 is the SPICE audio device

## Results: PipeWire quantum sweep (2026-04-16)

Played continuous audio (browser) while cycling through quantum values, 30s each.
ERR counter is cumulative; deltas show xruns per 30s window.

| Quantum | Latency | Xruns/30s |
| ------- | ------- | --------- |
| 256     | ~5.3ms  | ~2427     |
| 512     | ~10.7ms | 8         |
| 1024    | ~21.3ms | 3         |
| 2048    | ~42.7ms | 0         |
| 4096    | ~85.3ms | 0         |

**Conclusion**: quantum=2048 eliminates xruns. 42ms audio latency is acceptable
for media playback; only matters for real-time audio (DAW, voice chat).

## Files

- `pw-quantum-test.sh` — test script (cycles quantums, captures full `pw-top` output)
- `results/20260416T132850/` — full `pw-top` output per quantum value
