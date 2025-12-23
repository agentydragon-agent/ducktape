from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def pkg_dir() -> Path:
    """Root directory of this package resources."""
    return Path(__file__).parent


def specimens_definitions_root() -> Path:
    """Directory with specimen definitions ({repo}/{version}/issues/*.yaml, snapshots.yaml).

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
    expected_files = [specimens_root / "snapshots.yaml"]
    missing = [f for f in expected_files if not f.exists()]
    if missing:
        raise FileNotFoundError(
            f"Specimens root missing required files: {', '.join(f.name for f in missing)}\n"
            f"Expected files in {specimens_root}"
        )

    return specimens_root
