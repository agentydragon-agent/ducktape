"""Explicit executable resolution and non-secret binary evidence."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_binary(name: str, override: str | None) -> dict[str, Any]:
    candidate = Path(override).expanduser() if override else Path(shutil.which(name) or "")
    if not candidate or not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise FileNotFoundError(f"unable to resolve executable for {name}; pass --{name}-bin")
    real = candidate.resolve()
    stat = real.stat()
    metadata: dict[str, Any] = {
        "requested_command": name,
        "resolver_method": "override" if override else "PATH",
        "resolved_path": str(real),
        "size": stat.st_size,
        "sha256": _digest(real),
    }
    try:
        result = subprocess.run([str(real), "--version"], capture_output=True, text=True, timeout=10, check=False)
        metadata["version_exit_code"] = result.returncode
        metadata["version_stdout"] = result.stdout[:4096]
        metadata["version_stderr"] = result.stderr[:4096]
    except (OSError, subprocess.TimeoutExpired) as error:
        metadata["version_probe_error"] = type(error).__name__
    return metadata
