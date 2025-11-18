from __future__ import annotations

from importlib import resources
from pathlib import Path


def _copy_tree(trav: resources.abc.Traversable, dest: Path) -> None:
    if trav.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(trav.read_text(encoding="utf-8"), encoding="utf-8")
        return
    dest.mkdir(parents=True, exist_ok=True)
    for child in trav.iterdir():
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
