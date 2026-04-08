"""Pre-commit hook installation and background environment setup.

Calls pre-commit's Python API directly rather than shelling out.
"""

import asyncio
import logging
from pathlib import Path

from pre_commit.commands.install_uninstall import install, install_hooks
from pre_commit.constants import VERSION as PRE_COMMIT_VERSION
from pre_commit.store import Store

logger = logging.getLogger(__name__)


async def install_precommit(project_dir: Path) -> None:
    """Install pre-commit hook and download hook environments. Raises on failure."""
    logger.info("pre-commit %s", PRE_COMMIT_VERSION)

    config_file = str(project_dir / ".pre-commit-config.yaml")
    git_dir = str(project_dir / ".git")
    store = Store()

    rc = await asyncio.to_thread(
        install, config_file=config_file, store=store, hook_types=None, overwrite=False, hooks=False, git_dir=git_dir
    )
    if rc != 0:
        raise RuntimeError(f"pre-commit install returned {rc}")

    logger.info("Installed git pre-commit hook")

    await asyncio.to_thread(install_hooks, config_file, store)
    logger.info("pre-commit hook environments installed")
