from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import NewType

# Public property ID type
PropertyID = NewType("PropertyID", str)


def pkg_dir() -> Path:
    """Root directory of this package resources."""
    return Path(__file__).parent


def props_definitions_root() -> Path:
    """Directory with property definition Markdown files (.../props)."""
    return pkg_dir() / "props"


def specimens_definitions_root() -> Path:
    """Directory with specimen definitions (issues/*.libsonnet, manifest.yaml, etc.)."""
    return pkg_dir() / "specimens"


def find_property_files(property_ids: list[str]) -> list[Path]:
    """Resolve property definition Markdown files by ID (filename stem)."""
    props_root = props_definitions_root()
    found: list[Path] = [md for md in props_root.rglob("*.md") if md.stem in set(property_ids)]
    return sorted(found, key=lambda p: p.as_posix())


@lru_cache(maxsize=1)
def _list_known_property_ids() -> set[PropertyID]:
    return {PropertyID(md.stem) for md in props_definitions_root().rglob("*.md")}


def validate_property_ids(props: list[PropertyID]) -> None:
    if not props:
        return
    known = _list_known_property_ids()
    unknown = set(props) - known
    if not unknown:
        return
    sample = ", ".join(sorted(str(k) for k in list(known)[:20]))
    raise ValueError(f"No such property: {', '.join(unknown)}. Known properties: {sample} ...")
