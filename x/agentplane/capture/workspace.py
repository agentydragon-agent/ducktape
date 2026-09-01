"""Synthetic-workspace snapshots; capture output and provider state never enter them."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def snapshot(root: Path, *, excluded: set[Path] | None = None) -> dict[str, Any]:
    root = root.resolve()
    ignored = {item.resolve() for item in excluded or set()}
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if any(path == item or item in path.parents for item in ignored):
            continue
        relative = path.relative_to(root).as_posix()
        stat = path.lstat()
        base: dict[str, Any] = {"path": relative, "mode": oct(stat.st_mode & 0o7777)}
        if path.is_symlink():
            base.update({"type": "symlink", "target": path.readlink()})
        elif path.is_dir():
            base["type"] = "directory"
        elif path.is_file():
            base.update({"type": "file", "size": stat.st_size, "sha256": _digest(path)})
        else:
            base["type"] = "other"
        entries.append(base)
    canonical = "\n".join(f"{entry!r}" for entry in entries).encode()
    return {"entries": entries, "tree_sha256": hashlib.sha256(canonical).hexdigest()}


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    prior = {entry["path"]: entry for entry in before["entries"]}
    current = {entry["path"]: entry for entry in after["entries"]}
    return {
        "added": [current[key] for key in sorted(current.keys() - prior.keys())],
        "removed": [prior[key] for key in sorted(prior.keys() - current.keys())],
        "changed": [current[key] for key in sorted(current.keys() & prior.keys()) if current[key] != prior[key]],
    }
