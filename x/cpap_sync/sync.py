#!/usr/bin/env python3
"""Sync all files from an ez Share WiFi SD card to a local directory."""

import argparse
import sys
from pathlib import Path

from card import EZShareClient

DEFAULT_BASE = "http://192.168.4.1"
DEFAULT_OUTPUT = "/data/cpap"


def sync(client: EZShareClient, output_dir: Path) -> None:
    for entry in client.walk():
        dest = EZShareClient.local_path(output_dir, entry.img_url)
        if dest.exists():
            print(f"skip  {dest}")
            continue
        print(f"get   {dest}", flush=True)
        client.download(entry.img_url, dest)
        print(f"done  {dest} ({dest.stat().st_size} bytes)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = EZShareClient(args.base_url)
    print(f"Syncing card -> {output_dir}", flush=True)
    sync(client, output_dir)
    print("Sync complete.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
