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
    defs_dir = props_root / "props"
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
    return {PropertyID(md.stem) for md in (properties_root() / "props").rglob("*.md")}


def validate_property_ids(props: list[PropertyID]) -> None:
    if not props:
        return
    known = _list_known_property_ids()
    unknown = set(props) - known
    if not unknown:
        return
    sample = ", ".join(sorted(str(k) for k in list(known)[:20]))
    raise ValueError(f"No such property: {', '.join(unknown)}. Known properties: {sample} ...")
