from __future__ import annotations

from pathlib import Path
from typing import Iterable

EXCLUDES = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache"}


def iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        parts = set(p.parts)
        if parts & EXCLUDES:
            continue
        yield p


def read_snippet(path: Path, start: int, end: int | None, context: int = 0) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()
    s = max(1, start - context)
    e = min(len(lines), (end or start) + context)
    # 1-based indexing for display
    out = []
    for i in range(s, e + 1):
        out.append(f"{i:>5}: {lines[i - 1]}")
    return "\n".join(out)
