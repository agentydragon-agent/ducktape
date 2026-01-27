#!/usr/bin/python3
"""
Analyze SPICE latency measurement recordings.

Reads a recording directory produced by record.py and computes
input-to-display latency using pixel-diff or OpenAI vision API.

Usage:
    python analyze.py <recording-dir>              # pixel-diff (default)
    python analyze.py <recording-dir> --vision     # OpenAI vision API

Requirements:
    - python3-pil, numpy (system packages)
    - For --vision: openai package (installed by direnv), OPENAI_API_KEY
"""

import argparse
import base64
import datetime
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import openai
from PIL import Image

VISION_PROMPT = (
    "This is a screenshot of a desktop with two windows side by side. "
    "LEFT: a terminal running a measurement script that displays a Clock line like 'Clock: HH:MM:SS.mmm'. "
    "RIGHT: a SPICE remote desktop window showing vim/nvim (dark background). "
    "The vim buffer may contain timestamp strings typed as test input.\n\n"
    "Read BOTH windows carefully. Ignore vim ~ (tilde) empty-line markers, status bar, and mode indicator.\n\n"
    "Output JSON with:\n"
    '- "clock": the CURRENT time shown on the Clock: line in the left terminal (e.g. "02:34:56.789"), or null if not visible. '
    "The clock updates rapidly; if you see multiple overlapping values, read the most recent one.\n"
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

VISION_CACHE_DIR = Path.home() / ".cache" / "spice-latency" / "vision"


def _vision_cache_key(image_path: Path) -> str:
    """Cache key from prompt hash + image content hash."""
    prompt_hash = hashlib.sha256(VISION_PROMPT.encode()).hexdigest()[:12]
    image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()[:16]
    return f"{prompt_hash}_{image_hash}"


def analyze_pixeldiff(
    frame_files: list[Path], keystroke_times: list[float], recording_start: float, recording_duration: float
) -> list[float | None]:
    """Pixel-diff analysis. Returns list of latencies (ms) per keystroke, None on failure."""
    if len(frame_files) < 2:
        print(f"  Not enough frames ({len(frame_files)})")
        return [None] * len(keystroke_times)

    actual_fps = len(frame_files) / recording_duration
    print(f"  Pixel-diff: {actual_fps:.1f} actual fps ({len(frame_files)} frames in {recording_duration:.1f}s)")

    diffs = []
    prev_arr = None
    for i, frame_file in enumerate(frame_files):
        arr = np.array(Image.open(frame_file).convert("L"))
        if prev_arr is not None:
            changed_pixels = int(np.sum(np.abs(arr.astype(np.int16) - prev_arr.astype(np.int16)) > 10))
            diffs.append((i, changed_pixels))
        prev_arr = arr

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


def analyze_vision(frame_files: list[Path], sent_timestamps: list[str]) -> list[float | None]:
    """Vision API analysis. Returns list of latencies (ms) per keystroke, None on failure."""
    client = openai.OpenAI()
    VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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

        try:
            fmt = "%H:%M:%S.%f"
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
        description="Analyze SPICE latency measurement recordings",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("recording_dir", type=Path, help="Path to recording directory from record.py")
    parser.add_argument("--vision", action="store_true", help="Use OpenAI vision API (default: pixel-diff)")
    args = parser.parse_args()

    metadata_path = args.recording_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"Error: {metadata_path} not found")
        sys.exit(1)

    metadata = json.loads(metadata_path.read_text())
    sent_timestamps = metadata["sent_timestamps"]
    frame_dir = args.recording_dir / "frames"
    frame_files = sorted(frame_dir.glob("frame_*.png"))

    print(f"Recording: {args.recording_dir}")
    print(f"  {len(frame_files)} frames, {len(sent_timestamps)} samples")
    print()

    if args.vision:
        print("Analyzing with vision API...")
        latencies = analyze_vision(frame_files, sent_timestamps)
    else:
        print("Analyzing with pixel-diff...")
        latencies = analyze_pixeldiff(
            frame_files, metadata["keystroke_perf_times"], metadata["recording_start"], metadata["recording_duration"]
        )

    print()
    print("=" * 50)
    print("Results:")
    valid_latencies = []
    for i, (ts, lat) in enumerate(zip(sent_timestamps, latencies, strict=True)):
        if lat is not None:
            valid_latencies.append(lat)
            print(f"  [{i + 1}] {ts} \u2192 {lat:.1f}ms")
        else:
            print(f"  [{i + 1}] {ts} \u2192 FAILED")

    if valid_latencies:
        avg = sum(valid_latencies) / len(valid_latencies)
        print(f"\n  Successful: {len(valid_latencies)}/{len(sent_timestamps)}")
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


if __name__ == "__main__":
    main()
