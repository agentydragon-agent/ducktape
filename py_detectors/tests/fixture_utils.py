from __future__ import annotations

from collections.abc import Iterator
from importlib import resources
from pathlib import Path

# Directories to skip when iterating over fixture resources (contain binary files)
_SKIP_DIRS = {"__pycache__"}


def iter_children(trav: resources.abc.Traversable) -> Iterator[resources.abc.Traversable]:
    """Iterate over children, skipping __pycache__ and other non-fixture directories."""
    for child in trav.iterdir():
        if child.name not in _SKIP_DIRS:
            yield child


def _copy_tree(trav: resources.abc.Traversable, dest: Path) -> None:
    if trav.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(trav.read_text(encoding="utf-8"), encoding="utf-8")
        return
    if trav.name in _SKIP_DIRS:
        return
    dest.mkdir(parents=True, exist_ok=True)
    for child in iter_children(trav):
        if child.is_file():
            (dest / child.name).write_text(child.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            _copy_tree(child, dest / child.name)


def copy_fixture(root: Path, package: str, name: str, dest_rel: str) -> Path:
    """Copy a fixture file or directory from importlib.resources into a temp repo.

    - package: dotted package path, e.g. 'tests.detectors.fixtures.positive'
    - name: file name (e.g., 'x.py') or directory name (multi-file fixture)
    - dest_rel: relative destination path under root
    Returns the destination path (file or directory path).
    """
    base = resources.files(package)
    trav = base.joinpath(name)
    dest = root / dest_rel
    _copy_tree(trav, dest)
    return dest
