"""PostToolUse hook: auto-format files after Edit/Write tool calls.

Runs pre-commit on files that Claude Code just modified. Delegates all
formatter dispatch to pre-commit's own configuration (.pre-commit-config.yaml),
maintaining a single source of truth for file-to-formatter mapping.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)

logger = logging.getLogger(__name__)

FILE_MODIFYING_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})


def _get_file_path(tool_input: dict[str, Any]) -> Path | None:
    file_path = tool_input.get("file_path")
    if file_path is None:
        return None
    return Path(file_path)


def _find_git_root(start: Path) -> Path | None:
    current = start if start.is_dir() else start.parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _run_precommit(file_path: Path, project_dir: Path) -> bool:
    """Run pre-commit on a single file. Returns True if the file was modified."""
    precommit = shutil.which("pre-commit")
    if precommit is None:
        return False

    original_content = file_path.read_bytes()

    subprocess.run(
        [precommit, "run", "--files", str(file_path)], check=False, cwd=project_dir, capture_output=True, timeout=30
    )
    # pre-commit returns non-zero when hooks fail or modify files.
    # We don't care about the exit code — only whether the file changed.

    return file_path.read_bytes() != original_content


def evaluate(hook_input: PostToolUseInput) -> PostToolUseOutput | None:
    if hook_input.tool_name not in FILE_MODIFYING_TOOLS:
        return None

    file_path = _get_file_path(hook_input.tool_input)
    if file_path is None or not file_path.exists():
        return None

    project_dir = _find_git_root(file_path)
    if project_dir is None:
        return None

    try:
        changed = _run_precommit(file_path, project_dir)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("pre-commit failed on %s: %s", file_path, e)
        return None

    if not changed:
        return None

    return PostToolUseOutput(
        hook_specific_output=PostToolUseHookSpecificOutput(
            additional_context=f"Auto-formatted {file_path.name} via pre-commit. File updated in-place."
        )
    )
