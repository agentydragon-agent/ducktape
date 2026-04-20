#!/usr/bin/env python3
"""Sync all files from an ez Share WiFi SD card to a local directory.

Uses the card's XML API (/client?command=GETFILELIST) to walk the directory tree.

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


def _listdir(url: str) -> tuple[list[str], list[str]]:
    """Fetch a GETFILELIST response and return (dir_urls, file_download_urls).

    type=3 entries are directories; their imgURL is the recursive GETFILELIST URL.
    type=4 entries are files; their imgURL is the download URL (8.3 short filename).
    Entries named '.' and '..' are skipped.
    """
    with urllib.request.urlopen(url) as r:
        data = r.read().replace(b'encoding="gb2312"', b"")
    root = ET.fromstring(data)
    dirs: list[str] = []
    files: list[str] = []
    for f in root.findall(".//file"):
        name = f.findtext("name") or ""
        img_url = f.findtext("imgURL") or ""
        if f.get("type") == "3":
            if name not in (".", ".."):
                dirs.append(img_url)
        elif f.get("type") == "4":
            files.append(img_url)
    return dirs, files


def _local_path(output_dir: Path, download_url: str) -> Path:
    """Map a download URL to a local path, preserving the card's directory structure.

    Download URLs look like: /download?file=DATALOG%5C20260418%5C202604~1.EDF
    Uses 8.3 short filenames (matching what's already on the PVC from initial sync).
    """
    qs = urllib.parse.urlparse(download_url).query
    file_param = urllib.parse.parse_qs(qs).get("file", [""])[0]
    rel = file_param.replace("\\", "/").lstrip("/")
    return output_dir / rel


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url) as r, tmp.open("wb") as f:
        while chunk := r.read(65536):
            f.write(chunk)
    tmp.rename(dest)


def sync(base: str, output_dir: Path) -> None:
    queue = [f"{base}/client?command=GETFILELIST&dir=A%3A"]
    visited: set[str] = set()
    while queue:
        url = queue.pop()
        if url in visited:
            continue
        visited.add(url)
        dirs, files = _listdir(url)
        queue.extend(dirs)
        for file_url in files:
            dest = _local_path(output_dir, file_url)
            if dest.exists():
                print(f"skip  {dest}")
                continue
            print(f"get   {dest}", flush=True)
            _download(file_url, dest)
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
