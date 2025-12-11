from __future__ import annotations

from functools import lru_cache
import logging
import os
from pathlib import Path
from typing import NewType

logger = logging.getLogger(__name__)

# Public property ID type
PropertyID = NewType("PropertyID", str)


def pkg_dir() -> Path:
    """Root directory of this package resources."""
    return Path(__file__).parent


def props_definitions_root() -> Path:
    """Directory with property definition Markdown files (.../props)."""
    return pkg_dir() / "props"


def specimens_definitions_root() -> Path:
    """Directory with specimen definitions ({repo}/{version}/issues/*.libsonnet, snapshots.yaml, lib.libsonnet).

    Requires ADGN_PROPS_SPECIMENS_ROOT environment variable to be set.

    Returns:
        Path to specimens directory (guaranteed to exist with required files)

    Raises:
        ValueError: If ADGN_PROPS_SPECIMENS_ROOT is not set
        FileNotFoundError: If specimens directory doesn't exist or missing required files
    """
    env_path = os.environ.get("ADGN_PROPS_SPECIMENS_ROOT")

    if not env_path:
        raise ValueError(
            "ADGN_PROPS_SPECIMENS_ROOT environment variable not set. "
            "Run from devenv shell (direnv allow) or set the variable manually."
        )

    specimens_root = Path(env_path).resolve()
    logger.debug(f"Using specimens root from ADGN_PROPS_SPECIMENS_ROOT: {specimens_root}")

    if not specimens_root.exists():
        raise FileNotFoundError(f"Specimens directory not found: {specimens_root}")

    # Validate expected structure exists
    expected_files = [specimens_root / "snapshots.yaml", specimens_root / "lib.libsonnet"]
    missing = [f for f in expected_files if not f.exists()]
    if missing:
        raise FileNotFoundError(
            f"Specimens root missing required files: {', '.join(f.name for f in missing)}\n"
            f"Expected files in {specimens_root}"
        )

    return specimens_root


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
