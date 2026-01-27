#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "dasbus"]
# ///
"""
SPICE input-to-display latency measurement (Wayland/GNOME).

Measures end-to-end latency: keystroke on client → character visible in SPICE window.

Setup:
    1. Open SPICE client to VM on atlas
    2. In VM: switch to VT, open nvim in insert mode:
       nvim --clean -c "set guicursor=a:blinkon0" -c "startinsert"
    3. Run this script on atlas

Requirements:
    - ffmpeg, ydotool (installed via ansible/atlas.yaml)
    - ydotoold running (systemd service)
    - uv (for automatic Python dependency management)
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dasbus.connection import SessionMessageBus
from PIL import Image


def find_spice_window_rect() -> tuple[int, int, int, int] | None:
    """Find SPICE window rectangle via GNOME Shell eval. Returns (x, y, w, h) or None."""
    bus = SessionMessageBus()
    shell = bus.get_proxy("org.gnome.Shell", "/org/gnome/Shell")

    js = """
    (function() {
        let found = global.get_window_actors().find(
            a => a.meta_window.title.includes("remote-viewer") ||
                 a.meta_window.title.includes("SPICE") ||
                 a.meta_window.title.includes("virt-viewer")
        );
        if (!found) return "null";
        let r = found.meta_window.get_frame_rect();
        return JSON.stringify({x: r.x, y: r.y, width: r.width, height: r.height});
    })()
    """

    success, result = shell.Eval(js)
    if not success or result == "null":
        return None

    rect = json.loads(result)
    return rect["x"], rect["y"], rect["width"], rect["height"]


def start_screencast(
    bus: SessionMessageBus, fps: int, output_path: Path, region: tuple[int, int, int, int] | None = None
) -> tuple:
    """Start GNOME Shell screencast via D-Bus. Returns (proxy, filename)."""
    screencast = bus.get_proxy("org.gnome.Shell.Screencast", "/org/gnome/Shell/Screencast")

    options = {"framerate": fps, "draw-cursor": False}

    if region:
        x, y, w, h = region
        success, filename = screencast.ScreencastArea(x, y, w, h, str(output_path), options)
    else:
        success, filename = screencast.Screencast(str(output_path), options)

    if not success:
        raise RuntimeError("Failed to start GNOME screencast")

    return screencast, str(filename)


def stop_screencast(screencast) -> None:
    """Stop an active GNOME Shell screencast."""
    screencast.StopScreencast()


def send_keystroke(key: str = "x") -> float:
    """Send keystroke via ydotool, return timestamp."""
    timestamp = time.perf_counter()
    subprocess.run(["ydotool", "key", key], check=True, capture_output=True)
    return timestamp


def analyze_frames(video_path: Path, keystroke_time: float, recording_start: float, fps: int) -> dict:
    """Analyze video frames to find when display changed after keystroke."""
    frame_dir = video_path.parent / "frames"
    frame_dir.mkdir(exist_ok=True)

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vsync", "0", str(frame_dir / "frame_%05d.png")],
        check=False,
        capture_output=True,
    )

    frame_files = sorted(frame_dir.glob("frame_*.png"))
    if len(frame_files) < 2:
        return {"error": f"Not enough frames extracted ({len(frame_files)})"}

    keystroke_offset = keystroke_time - recording_start
    keystroke_frame = int(keystroke_offset * fps)

    print(f"  Keystroke at {keystroke_offset:.3f}s into recording (frame ~{keystroke_frame})")
    print(f"  Total frames extracted: {len(frame_files)}")

    # Compute frame diffs
    diffs = []
    prev_img = None

    for i, frame_file in enumerate(frame_files):
        img = Image.open(frame_file).convert("L")  # Grayscale

        if prev_img is not None:
            diff = sum(abs(a - b) for a, b in zip(img.tobytes(), prev_img.tobytes(), strict=True))
            diff_normalized = diff / (img.width * img.height)
            diffs.append((i, diff_normalized))

        prev_img = img

    if not diffs:
        return {"error": "No frame diffs computed"}

    median_diff = sorted(d[1] for d in diffs)[len(diffs) // 2]
    threshold = max(median_diff * 3, 0.5)

    print(f"  Median frame diff: {median_diff:.2f}, threshold: {threshold:.2f}")

    change_frame = None
    for frame_idx, diff in diffs:
        if frame_idx > keystroke_frame and diff > threshold:
            change_frame = frame_idx
            print(f"  Change detected at frame {frame_idx} (diff={diff:.2f})")
            break

    if change_frame is None:
        top_diffs = sorted(diffs, key=lambda x: x[1], reverse=True)[:5]
        print(f"  No change detected. Top diffs: {top_diffs}")
        return {"error": "No display change detected after keystroke"}

    change_time = change_frame / fps
    latency_sec = change_time - keystroke_offset
    latency_ms = latency_sec * 1000

    # Cleanup frames
    for f in frame_files:
        f.unlink()
    frame_dir.rmdir()

    return {"keystroke_frame": keystroke_frame, "change_frame": change_frame, "latency_ms": latency_ms, "fps": fps}


def measure_once(
    bus: SessionMessageBus,
    key: str = "x",
    fps: int = 60,
    region: tuple[int, int, int, int] | None = None,
    work_dir: Path | None = None,
) -> float | None:
    """Perform one latency measurement. Returns latency in ms, or None on failure."""
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="spice_latency_"))

    video_path = work_dir / "recording.webm"

    print(f"  Starting screencast at {fps}fps...")
    screencast, filename = start_screencast(bus, fps, video_path, region=region)
    recording_start = time.perf_counter()

    # Wait for recording to stabilize
    time.sleep(1.0)

    print("  Sending keystroke...")
    keystroke_time = send_keystroke(key)

    # Wait for the change to be captured
    time.sleep(1.0)

    print("  Stopping screencast...")
    stop_screencast(screencast)
    recording_end = time.perf_counter()

    actual_path = Path(filename)
    print(f"  Recording complete ({recording_end - recording_start:.1f}s), file: {actual_path}")

    if not actual_path.exists():
        print(f"  Error: recording file not found at {actual_path}")
        return None

    # Analyze
    print("  Analyzing frames...")
    result = analyze_frames(actual_path, keystroke_time, recording_start, fps)

    if "error" in result:
        print(f"  Error: {result['error']}")
        return None

    return result["latency_ms"]


def main():
    parser = argparse.ArgumentParser(
        description="Measure SPICE input-to-display latency (Wayland/GNOME)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--samples", type=int, default=10, help="Number of measurements")
    parser.add_argument("--fps", type=int, default=60, help="Recording framerate")
    parser.add_argument("--key", type=str, default="x", help="Key to press")
    parser.add_argument("--keep-video", action="store_true", help="Keep video files for debugging")

    args = parser.parse_args()

    # Preflight checks
    if not shutil.which("ydotool"):
        print("Error: ydotool not found. Install via: sudo apt install ydotool")
        sys.exit(1)
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found. Install via: sudo apt install ffmpeg")
        sys.exit(1)

    print("SPICE Latency Measurement (Wayland/GNOME)")
    print("==========================================")

    # Find SPICE window
    print("Looking for SPICE window...")
    region = find_spice_window_rect()
    if not region:
        print("Error: SPICE window not found. Make sure remote-viewer or virt-viewer is running.")
        sys.exit(1)
    x, y, w, h = region
    print(f"Found SPICE window: {w}x{h} at ({x},{y})")

    print(f"Samples: {args.samples}, FPS: {args.fps}, Key: {args.key}")
    print()

    bus = SessionMessageBus()
    latencies = []
    work_dir = Path(tempfile.mkdtemp(prefix="spice_latency_"))

    for i in range(args.samples):
        print(f"Measurement {i + 1}/{args.samples}:")
        latency = measure_once(bus, key=args.key, fps=args.fps, region=region, work_dir=work_dir)

        if latency is not None:
            latencies.append(latency)
            print(f"  Latency: {latency:.1f}ms")
        else:
            print("  Measurement failed")
        print()

        time.sleep(0.5)

    # Summary
    print("=" * 40)
    print("Results:")
    if latencies:
        avg = sum(latencies) / len(latencies)
        min_l = min(latencies)
        max_l = max(latencies)
        print(f"  Samples: {len(latencies)}/{args.samples}")
        print(f"  Average: {avg:.1f}ms")
        print(f"  Min: {min_l:.1f}ms")
        print(f"  Max: {max_l:.1f}ms")

        if avg < 50:
            print("  Rating: Excellent (<50ms)")
        elif avg < 100:
            print("  Rating: Good (50-100ms)")
        elif avg < 200:
            print("  Rating: Noticeable (100-200ms)")
        else:
            print("  Rating: Laggy (>200ms)")
    else:
        print("  No successful measurements")

    if not args.keep_video:
        shutil.rmtree(work_dir, ignore_errors=True)
    else:
        print(f"\nVideo files kept in: {work_dir}")


if __name__ == "__main__":
    main()
