#!/usr/bin/env python3
"""Deterministic, workspace-local operation probe used only by live captures.

It never accesses paths outside its working directory. ``count`` persists a counter so a
replayed model/tool action is observable; ``wait`` exposes an interrupt window; ``fail``
creates reproducible stdout and stderr evidence before returning a non-zero status.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("echo", "count", "wait", "fail"))
    parser.add_argument("--value", default="CAPTURE_PROBE")
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    state = root / ".agentplane-probe-count.json"
    if args.mode == "echo":
        print(args.value)
        return 0
    if args.mode == "count":
        count = json.loads(state.read_text())["count"] if state.exists() else 0
        state.write_text(json.dumps({"count": count + 1}) + "\n")
        print(f"count={count + 1}")
        return 0
    if args.mode == "wait":
        print("wait_started", flush=True)
        time.sleep(args.seconds)
        print("wait_finished", flush=True)
        return 0
    print("probe stdout before failure", flush=True)
    print("probe stderr before failure", flush=True, file=__import__("sys").stderr)
    return 23


if __name__ == "__main__":
    raise SystemExit(main())
