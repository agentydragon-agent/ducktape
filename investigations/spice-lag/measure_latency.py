#!/usr/bin/python3
"""
SPICE input-to-display latency measurement (Wayland/GNOME).

Embeds a millisecond clock in the terminal display. Each recorded frame
contains both the clock reading (host time) and the SPICE window state.
The vision API reads both from the same frame to compute latency.

Setup:
    1. cd investigations/spice-lag (direnv creates venv with system-site-packages + openai)
    2. Open SPICE client to VM on atlas, place window on right half of screen
    3. In VM: open nvim in insert mode:
       nvim --clean -c "set guicursor=a:blinkon0" -c "startinsert"
    4. Open a terminal on atlas for this script, place on left half
    5. Run: python measure_latency.py [--vision]

Requirements:
    - ffmpeg, ydotool (installed via ansible/atlas.yaml)
    - ydotoold running
    - python3-gi, python3-pil (system packages, installed with GNOME)
    - For --vision: OPENAI_API_KEY in environment, openai package (installed by direnv)
"""

import argparse
import base64
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import gi
import openai

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402
from PIL import Image  # noqa: E402

VISION_PROMPT = (
    "This is a screenshot of a desktop with two windows side by side. "
    "LEFT: a terminal running a measurement script that displays a Clock line like 'Clock: HH:MM:SS.mmm'. "
    "RIGHT: a SPICE remote desktop window showing vim/nvim (dark background). "
    "The vim buffer may contain timestamp strings typed as test input.\n\n"
    "Read BOTH windows carefully. Ignore vim ~ (tilde) empty-line markers, status bar, and mode indicator.\n\n"
    "Output JSON with:\n"
    '- "clock": the time shown on the Clock: line in the left terminal (e.g. "02:34:56.789"), or null if not visible\n'
    '- "vim_buffer_text": array of actual text lines in the vim buffer (exclude ~ lines)'
)

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "clock": {"type": ["string", "null"]},
        "vim_buffer_text": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["clock", "vim_buffer_text"],
    "additionalProperties": False,
}


def _session_bus() -> Gio.DBusConnection:
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _dbus_call(
    bus: Gio.DBusConnection,
    bus_name: str,
    object_path: str,
    interface: str,
    method: str,
    params: GLib.Variant | None = None,
    reply_type: GLib.VariantType | None = None,
) -> GLib.Variant:
    return bus.call_sync(bus_name, object_path, interface, method, params, reply_type, Gio.DBusCallFlags.NONE, -1, None)


def start_screencast(bus: Gio.DBusConnection, fps: int, output_path: Path) -> str:
    """Start GNOME Shell full-screen screencast. Returns filename."""
    builder = GLib.VariantBuilder.new(GLib.VariantType("(sa{sv})"))
    builder.add_value(GLib.Variant("s", str(output_path)))
    options_builder = GLib.VariantBuilder.new(GLib.VariantType("a{sv}"))
    options_builder.add_value(GLib.Variant("{sv}", ("framerate", GLib.Variant("i", fps))))
    options_builder.add_value(GLib.Variant("{sv}", ("draw-cursor", GLib.Variant("b", False))))
    builder.add_value(options_builder.end())
    params = builder.end()

    result = _dbus_call(
        bus,
        "org.gnome.Shell.Screencast",
        "/org/gnome/Shell/Screencast",
        "org.gnome.Shell.Screencast",
        "Screencast",
        params,
        GLib.VariantType("(bs)"),
    )

    success = result.get_child_value(0).get_boolean()
    filename = result.get_child_value(1).get_string()
    if not success:
        raise RuntimeError("Failed to start GNOME screencast")
    return filename


def stop_screencast(bus: Gio.DBusConnection) -> None:
    """Stop an active GNOME Shell screencast."""
    _dbus_call(
        bus, "org.gnome.Shell.Screencast", "/org/gnome/Shell/Screencast", "org.gnome.Shell.Screencast", "StopScreencast"
    )


def _now_str() -> str:
    """Current wall-clock time as HH:MM:SS.mmm."""
    now = datetime.datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def run_clock(stop_event: threading.Event) -> None:
    """Print rapidly updating clock to terminal until stop_event is set."""
    while not stop_event.is_set():
        sys.stdout.write(f"\rClock: {_now_str()}  ")
        sys.stdout.flush()
        time.sleep(0.010)
    # Clear the clock line
    sys.stdout.write("\r" + " " * 40 + "\r")
    sys.stdout.flush()


def type_timestamp() -> str:
    """Type current timestamp into focused window via ydotool. Returns the timestamp string."""
    ts = _now_str()
    subprocess.run(["ydotool", "type", ts + "\n"], check=True, capture_output=True)
    return ts


def extract_frames(video_path: Path, frame_dir: Path) -> list[Path]:
    """Extract all frames from video as PNGs. Returns sorted list of frame paths."""
    frame_dir.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vsync", "0", str(frame_dir / "frame_%05d.png")],
        check=False,
        capture_output=True,
    )
    return sorted(frame_dir.glob("frame_*.png"))


def analyze_pixeldiff(
    frame_files: list[Path], keystroke_times: list[float], recording_start: float, recording_duration: float
) -> list[float | None]:
    """Pixel-diff analysis. Returns list of latencies (ms) per keystroke, None on failure."""
    if len(frame_files) < 2:
        print(f"  Not enough frames ({len(frame_files)})")
        return [None] * len(keystroke_times)

    actual_fps = len(frame_files) / recording_duration
    print(f"  Pixel-diff: {actual_fps:.1f} actual fps ({len(frame_files)} frames in {recording_duration:.1f}s)")

    # Compute per-frame diffs
    diffs = []
    prev_img = None
    for i, frame_file in enumerate(frame_files):
        img = Image.open(frame_file).convert("L")
        img_bytes = img.tobytes()
        if prev_img is not None:
            pixel_diffs = [abs(a - b) for a, b in zip(img_bytes, prev_img, strict=True)]
            changed_pixels = sum(1 for d in pixel_diffs if d > 10)
            diffs.append((i, changed_pixels))
        prev_img = img_bytes

    if not diffs:
        return [None] * len(keystroke_times)

    median_diff = sorted(d[1] for d in diffs)[len(diffs) // 2]
    threshold = max(median_diff * 3, 50)
    print(f"  Median changed pixels: {median_diff}, threshold: {threshold:.0f}")

    results = []
    for keystroke_time in keystroke_times:
        keystroke_offset = keystroke_time - recording_start
        keystroke_frame = int(keystroke_offset * actual_fps)

        change_frame = None
        for frame_idx, diff in diffs:
            if frame_idx > keystroke_frame and diff > threshold:
                change_frame = frame_idx
                break

        if change_frame is None:
            results.append(None)
        else:
            change_time = change_frame / actual_fps
            latency_ms = (change_time - keystroke_offset) * 1000
            results.append(latency_ms)

    return results


VISION_CACHE_DIR = Path.home() / ".cache" / "spice-latency" / "vision"


def _vision_cache_key(image_path: Path) -> str:
    """Cache key from prompt hash + image content hash."""
    prompt_hash = hashlib.sha256(VISION_PROMPT.encode()).hexdigest()[:12]
    image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()[:16]
    return f"{prompt_hash}_{image_hash}"


def analyze_vision(frame_files: list[Path], sent_timestamps: list[str]) -> list[float | None]:
    """Vision API analysis. Returns list of latencies (ms) per keystroke, None on failure."""
    client = openai.OpenAI()
    VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Analyze each frame
    frame_results = []
    cache_hits = 0
    for i, frame_file in enumerate(frame_files):
        cache_key = _vision_cache_key(frame_file)
        cache_file = VISION_CACHE_DIR / f"{cache_key}.json"
        if cache_file.exists():
            result = json.loads(cache_file.read_text())
            cache_hits += 1
        else:
            image_b64 = base64.b64encode(frame_file.read_bytes()).decode()
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"},
                            },
                        ],
                    }
                ],
                max_tokens=256,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "frame_analysis", "strict": True, "schema": VISION_SCHEMA},
                },
            )
            result = json.loads(resp.choices[0].message.content)
            cache_file.write_text(json.dumps(result, indent=2))

        frame_results.append(result)
        if (i + 1) % 10 == 0 or i == len(frame_files) - 1:
            print(f"  Vision: analyzed {i + 1}/{len(frame_files)} frames ({cache_hits} cache hits)")

    # For each sent timestamp, find first frame where it appears in vim_buffer_text
    results = []
    for ts in sent_timestamps:
        first_clock = None
        for i, fr in enumerate(frame_results):
            vim_text = " ".join(fr.get("vim_buffer_text", []))
            if ts in vim_text:
                first_clock = fr.get("clock")
                print(f"  Timestamp '{ts}' first seen in frame {i + 1}, clock={first_clock}")
                break

        if first_clock is None:
            print(f"  Timestamp '{ts}' not found in any frame")
            results.append(None)
            continue

        # Parse clock strings to compute latency
        try:
            fmt = "%H:%M:%S.%f"
            # Pad milliseconds to microseconds for parsing
            clock_padded = first_clock + "000" if len(first_clock.split(".")[-1]) == 3 else first_clock
            ts_padded = ts + "000" if len(ts.split(".")[-1]) == 3 else ts
            t_display = datetime.datetime.strptime(clock_padded, fmt)
            t_sent = datetime.datetime.strptime(ts_padded, fmt)
            latency_ms = (t_display - t_sent).total_seconds() * 1000
            results.append(latency_ms)
        except (ValueError, TypeError) as e:
            print(f"  Failed to parse timestamps: clock={first_clock}, sent={ts}: {e}")
            results.append(None)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Measure SPICE input-to-display latency (Wayland/GNOME)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--samples", type=int, default=3, help="Number of measurements")
    parser.add_argument("--fps", type=int, default=120, help="Recording framerate (requested)")
    parser.add_argument("--vision", action="store_true", help="Use OpenAI vision API for frame analysis")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between keystrokes")
    args = parser.parse_args()

    for tool in ["ydotool", "ffmpeg"]:
        if not shutil.which(tool):
            print(f"Error: {tool} not found")
            sys.exit(1)

    print("SPICE Latency Measurement (Wayland/GNOME)")
    print("==========================================")
    print("Place measurement terminal on LEFT, SPICE window on RIGHT.")
    print(f"Samples: {args.samples}, FPS: {args.fps}, Vision: {args.vision}")
    print()

    bus = _session_bus()
    work_dir = Path(tempfile.mkdtemp(prefix="spice_latency_"))
    video_path = work_dir / "recording.webm"

    # Start single screencast for all measurements
    print(f"Starting screencast at {args.fps}fps...")
    filename = start_screencast(bus, args.fps, video_path)
    recording_start = time.perf_counter()

    # Start live clock display
    clock_stop = threading.Event()
    clock_thread = threading.Thread(target=run_clock, args=(clock_stop,), daemon=True)
    clock_thread.start()

    # Wait for recording to stabilize
    time.sleep(1.0)

    # Send keystrokes
    sent_timestamps = []
    keystroke_perf_times = []
    for i in range(args.samples):
        ts = type_timestamp()
        perf_time = time.perf_counter()
        sent_timestamps.append(ts)
        keystroke_perf_times.append(perf_time)
        # Print on a new line (clock uses \r on current line)
        sys.stdout.write(f"\n  [{i + 1}/{args.samples}] Sent: {ts}\n")
        sys.stdout.flush()
        if i < args.samples - 1:
            time.sleep(args.delay)

    # Wait for last keystroke to be captured
    time.sleep(3.0)

    # Stop clock and screencast
    clock_stop.set()
    clock_thread.join()
    stop_screencast(bus)
    recording_end = time.perf_counter()
    recording_duration = recording_end - recording_start

    actual_path = Path(filename)
    print(f"Recording complete ({recording_duration:.1f}s), file: {actual_path}")

    if not actual_path.exists():
        print(f"Error: recording file not found at {actual_path}")
        sys.exit(1)

    # Extract frames
    print("Extracting frames...")
    frame_dir = work_dir / "frames"
    frame_files = extract_frames(actual_path, frame_dir)
    print(f"  {len(frame_files)} frames extracted")

    # Analyze
    if args.vision:
        print("Analyzing with vision API...")
        latencies = analyze_vision(frame_files, sent_timestamps)
    else:
        print("Analyzing with pixel-diff...")
        latencies = analyze_pixeldiff(frame_files, keystroke_perf_times, recording_start, recording_duration)

    # Report
    print()
    print("=" * 50)
    print("Results:")
    valid_latencies = []
    for i, (ts, lat) in enumerate(zip(sent_timestamps, latencies, strict=True)):
        if lat is not None:
            valid_latencies.append(lat)
            print(f"  [{i + 1}] {ts} → {lat:.1f}ms")
        else:
            print(f"  [{i + 1}] {ts} → FAILED")

    if valid_latencies:
        avg = sum(valid_latencies) / len(valid_latencies)
        print(f"\n  Successful: {len(valid_latencies)}/{args.samples}")
        print(f"  Average: {avg:.1f}ms")
        print(f"  Min: {min(valid_latencies):.1f}ms")
        print(f"  Max: {max(valid_latencies):.1f}ms")

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

    print(f"\nFiles kept in: {work_dir}")


if __name__ == "__main__":
    main()
