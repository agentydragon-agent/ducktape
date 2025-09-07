#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from gitea_api import ensure_mirror, trigger_sync


@dataclass(frozen=True)
class UrlKey:
    origin_url: str

    @property
    def host(self) -> str:
        from urllib.parse import urlparse

        p = urlparse(self.origin_url)
        return (p.hostname or p.netloc or "unknown").lower()

    @property
    def path(self) -> str:
        from urllib.parse import urlparse

        p = urlparse(self.origin_url)
        s = (p.path or "/").strip("/")
        return s[:-4] if s.endswith(".git") else s

    @property
    def storage_key_gitea(self) -> Tuple[str, str]:
        segs = [s for s in self.path.split("/") if s]
        if len(segs) < 2:
            raise ValueError(f"URL path too short for gitea layout: {self.path}")
        owner, repo = segs[-2], segs[-1]
        return owner, repo




def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    cp = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    return cp.returncode, cp.stdout, cp.stderr


def obtain(upstream: str, dest_root: Path, mount_point: str, base_url: str, token: str) -> int:
    key = UrlKey(upstream)
    owner, repo = key.storage_key_gitea

    # Ensure mirror (best-effort) then trigger a sync
    if base_url and token:
        ok, err = ensure_mirror(base_url, token, upstream, owner, repo)
        if not ok and err:
            print(f"warn: ensure_mirror: {err}", file=sys.stderr)
        ok, err = trigger_sync(base_url, token, owner, repo)
        if not ok and err:
            print(f"warn: trigger_sync: {err}", file=sys.stderr)

    # Clone with reference from mounted bare store
    rel = f"{owner}/{repo}.git"
    dest = dest_root / key.host / key.path
    dest.parent.mkdir(parents=True, exist_ok=True)

    ref_path = Path(mount_point) / rel
    ref_url = f"file://{ref_path}"

    cmd = [
        "sh",
        "-lc",
        (
            f"git clone --reference {shlex.quote(str(ref_path))} "
            f"{shlex.quote(ref_url)} {shlex.quote(str(dest))} && "
            f"git -C {shlex.quote(str(dest))} rev-parse HEAD"
        ),
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        print(err or out, file=sys.stderr)
        return rc
    print((out or "").strip())
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Ensure/sync a Gitea mirror and clone with reference")
    p.add_argument("url", help="Upstream http(s) URL for the repository (e.g., https://github.com/org/repo.git)")
    p.add_argument("--dest-root", default=os.environ.get("WORKING_DIR", "/workspace"))
    p.add_argument("--mount-point", default=os.environ.get("MOUNT_POINT", "/mnt/git-bare"))
    args = p.parse_args()

    base_url = os.environ.get("GITEA_BASE_URL", "")
    token = os.environ.get("GITEA_TOKEN", "")

    try:
        return obtain(
            upstream=args.url,
            dest_root=Path(args.dest_root),
            mount_point=args.mount_point,
            base_url=base_url,
            token=token,
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
