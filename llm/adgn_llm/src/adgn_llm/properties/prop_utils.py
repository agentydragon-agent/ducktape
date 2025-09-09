from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from functools import lru_cache
from typing import NewType

# Public property ID type
PropertyID = NewType("PropertyID", str)


def properties_root() -> Path:
    """Root directory for packaged properties (importlib.resources aware)."""
    return Path(str(files("adgn_llm").joinpath("properties")))


def find_property_files(property_ids: list[str]) -> list[Path]:
    """Resolve property definition Markdown files by ID (filename stem)."""
    props_root = properties_root()
    defs_dir = props_root / "definitions"
    wanted = set(property_ids)
    found: list[Path] = []
    if not defs_dir.exists():
        return found
    for md in defs_dir.rglob("*.md"):
        if md.stem in wanted:
            found.append(md)
    return sorted(found, key=lambda p: p.as_posix())


@lru_cache(maxsize=1)
def _list_known_property_ids() -> set[PropertyID]:
    defs_root = properties_root() / "definitions"
    ids: set[PropertyID] = set()
    if defs_root.exists():
        for md in defs_root.rglob("*.md"):
            ids.add(PropertyID(md.stem))
    return ids


def validate_property_ids(props: list[PropertyID]) -> None:
    if not props:
        return
    known = _list_known_property_ids()
    unknown = [p for p in props if p not in known]
    if unknown:
        sample = ", ".join(sorted(str(k) for k in list(known)[:20]))
        raise ValueError(
            f"Unknown property IDs: {', '.join(unknown)}. Known (sample): {sample} ...",
        )
