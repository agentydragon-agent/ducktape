"""Pre-commit hook installation and background environment setup.

Calls pre-commit's Python API directly rather than shelling out.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from pre_commit.commands.install_uninstall import install, install_hooks
from pre_commit.constants import VERSION as PRE_COMMIT_VERSION
from pre_commit.store import Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrecommitNotInstalled:
    """pre-commit hook was not installed (install failed, etc.)."""


@dataclass(frozen=True)
class PrecommitInstallingHooks:
    """pre-commit hook freshly installed and background `install-hooks` is running."""


PrecommitSetup = PrecommitNotInstalled | PrecommitInstallingHooks


@dataclass(frozen=True)
class PrecommitHooksInstalled:
    """install-hooks completed successfully."""


@dataclass(frozen=True)
class PrecommitHooksFailed:
    """install-hooks failed."""

    error: BaseException


PrecommitHooksResult = PrecommitHooksInstalled | PrecommitHooksFailed


async def install_precommit(project_dir: Path) -> tuple[PrecommitSetup, asyncio.Task[PrecommitHooksResult] | None]:
    """Install git pre-commit hook and eagerly pre-install hook environments.

    Calls pre-commit's Python API directly for hook installation. Fires off
    install_hooks() in a thread via asyncio.to_thread and returns the resulting
    Task so the caller can track completion and surface the outcome to Claude.

    Always runs install-hooks in the background, even if the hook file already
    exists. The hook file persists across sessions but ~/.cache/pre-commit/
    environments may not, so we always ensure environments are populated.

    Returns:
        (PrecommitSetup, task) where task is None if setup failed. The task
        resolves to PrecommitHooksResult (success or failure).
    """
    logger.info("pre-commit %s", PRE_COMMIT_VERSION)

    config_file = str(project_dir / ".pre-commit-config.yaml")
    git_dir = str(project_dir / ".git")
    store = Store()

    rc = await asyncio.to_thread(
        install, config_file=config_file, store=store, hook_types=None, overwrite=False, hooks=False, git_dir=git_dir
    )
    if rc != 0:
        logger.warning("pre-commit install returned %d", rc)
        return PrecommitNotInstalled(), None

    logger.info("Installed git pre-commit hook")

    # Fire off install-hooks via asyncio.to_thread so the server can track
    # completion and surface the result to Claude via pre_tool_use.
    # pre-commit uses flock on ~/.cache/pre-commit/.lock, so this is safe to
    # run concurrently with a hook-triggered run.
    async def _run_install_hooks() -> PrecommitHooksResult:
        try:
            await asyncio.to_thread(install_hooks, config_file, store)
            logger.info("Background pre-commit install-hooks completed")
            return PrecommitHooksInstalled()
        except BaseException as e:
            logger.exception("Background pre-commit install-hooks failed")
            return PrecommitHooksFailed(error=e)

    task: asyncio.Task[PrecommitHooksResult] = asyncio.create_task(
        _run_install_hooks(), name="pre-commit-install-hooks"
    )
    return PrecommitInstallingHooks(), task
