#!/usr/bin/env python3
"""Sync all files from an ez Share WiFi SD card to a local directory.

Usage: sync.py [--base-url URL] [--output-dir DIR] [--root-dir DIR]

The card exposes:
  /dir?dir=A:\\PATH   — HTML directory listing
  /download?file=... — file download (URL-encoded Windows path)
"""

import argparse
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_BASE = "http://ezshare.card"
DEFAULT_ROOT = "A:"
DEFAULT_OUTPUT = "/data/cpap"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)


def _listdir(base: str, path: str) -> tuple[list[str], list[str]]:
    """Return (subdirs, download_urls) for a card directory path like 'A:\\DATALOG'."""
    url = f"{base}/dir?dir={urllib.parse.quote(path, safe=':')}"
    with urllib.request.urlopen(url) as r:
        html = r.read().decode("gb2312", errors="replace")

    p = _LinkParser()
    p.feed(html)

    dirs: list[str] = []
    files: list[str] = []
    for link in p.links:
        if link.startswith("dir?dir="):
            raw = urllib.parse.unquote(link[len("dir?dir=") :])
            name = raw.split("\\")[-1]
            if name not in (".", ".."):
                dirs.append(raw)
        elif "/download?file=" in link:
            files.append(link if link.startswith("http") else f"{base}/{link}")
    return dirs, files


def _local_path(output_dir: Path, download_url: str) -> Path:
    """Map a download URL to a local path under output_dir.

    The card returns file params like "DATALOG\\\\20251004\\\\202510~1.EDF".
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


def sync(base: str, root: str, output_dir: Path) -> None:
    queue = [root]
    visited: set[str] = set()
    while queue:
        path = queue.pop()
        if path in visited:
            continue
        visited.add(path)
        dirs, files = _listdir(base, path)
        queue.extend(dirs)
        for url in files:
            dest = _local_path(output_dir, url)
            if dest.exists():
                print(f"skip  {dest}")
                continue
            print(f"get   {dest}", flush=True)
            _download(url, dest)
            print(f"done  {dest} ({dest.stat().st_size} bytes)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    ap.add_argument("--root-dir", default=DEFAULT_ROOT)
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Syncing {args.root_dir} -> {output_dir}", flush=True)
    sync(args.base_url, args.root_dir, output_dir)
    print("Sync complete.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
