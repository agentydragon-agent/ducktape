#!/usr/bin/env python3
"""Sync all files from an ez Share WiFi SD card to a local directory.

Uses the card's XML API (/client?command=Getallfiles) instead of HTML parsing.

Usage: sync.py [--base-url URL] [--output-dir DIR]
"""

import argparse
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_BASE = "http://192.168.4.1"
DEFAULT_OUTPUT = "/data/cpap"


def _get_xml(base: str, path: str) -> ET.Element:
    with urllib.request.urlopen(f"{base}{path}") as r:
        return ET.fromstring(r.read())


def _all_files(base: str) -> list[tuple[str, str]]:
    """Return (dir_attr, name) for every file on the card via Getallfiles XML API."""
    root = _get_xml(base, "/client?command=Getallfiles&fileType=0&ctime=0")
    return [(f.get("dir", ""), f.get("name", "")) for f in root.findall("file")]


def _local_path(output_dir: Path, dir_attr: str, name: str) -> Path:
    """Map a card FileEntry (dir, name) to a local path under output_dir.

    dir_attr is a Windows path like "A:\\DATALOG\\20260418" or "A:" for root.
    """
    rel = dir_attr.removeprefix("A:\\").removeprefix("A:").replace("\\", "/")
    return output_dir / rel / name if rel else output_dir / name


def _download_url(base: str, dir_attr: str, name: str) -> str:
    rel = dir_attr.removeprefix("A:\\").removeprefix("A:")
    file_param = f"{rel}\\{name}" if rel else name
    return f"{base}/download?file={urllib.parse.quote(file_param, safe='')}"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url) as r, tmp.open("wb") as f:
        while chunk := r.read(65536):
            f.write(chunk)
    tmp.rename(dest)


def sync(base: str, output_dir: Path) -> None:
    for dir_attr, name in _all_files(base):
        dest = _local_path(output_dir, dir_attr, name)
        if dest.exists():
            print(f"skip  {dest}")
            continue
        url = _download_url(base, dir_attr, name)
        print(f"get   {dest}", flush=True)
        _download(url, dest)
        print(f"done  {dest} ({dest.stat().st_size} bytes)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Syncing card -> {output_dir}", flush=True)
    sync(args.base_url, output_dir)
    print("Sync complete.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
