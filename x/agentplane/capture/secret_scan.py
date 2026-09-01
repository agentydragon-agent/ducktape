"""Small pre-commit guard for captured examples; it never redacts or rewrites data."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN = re.compile(rb"(\bbearer\s+[A-Za-z0-9._-]{12,}|\bsk-[A-Za-z0-9_-]{12,})", re.IGNORECASE)


def scan(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file() and FORBIDDEN.search(path.read_bytes()):
            raise ValueError(f"credential-shaped material in {path.name}")
