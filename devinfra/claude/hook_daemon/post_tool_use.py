"""PostToolUse hook: lint-check files after Edit/Write tool calls.

Runs pre-commit on files that Claude Code just modified. Hooks listed in
the pre_commit.auto_apply_hooks config keep their changes on disk. All
other hooks' changes are reverted and issues are reported back to the agent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygit2
from pydantic import ValidationError

from devinfra.claude.claude_api.hooks.output import HookOutput
from devinfra.claude.claude_api.hooks.post_tool_use import PostToolUseHookSpecificOutput, PostToolUseInput
from devinfra.claude.claude_api.tool_input_models import EditInput, WriteInput, _ToolInputBase
from devinfra.claude.hook_daemon import templates
from devinfra.claude.hook_daemon.config import PreCommitConfig
from devinfra.claude.hook_daemon.precommit_runner import (
    HookAutoApplied,
    HookFailedNotApplied,
    HookWouldEdit,
    RunResult,
    run_on_file,
)
from devinfra.claude.hook_daemon.tool_input_parsing import parse_tool_input

if TYPE_CHECKING:
    from devinfra.claude.hook_daemon.session import Session

logger = logging.getLogger(__name__)

FILE_MODIFYING_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})


def _get_file_path(parsed: _ToolInputBase | None, raw: dict[str, Any]) -> Path | None:
    """Extract file_path from parsed model, falling back to raw dict for unknown tools."""
    if isinstance(parsed, (EditInput, WriteInput)):
        return Path(parsed.file_path)
    # Fallback for MultiEdit or parse failure — read from raw dict.
    raw_path = raw.get("file_path")
    return Path(raw_path) if raw_path is not None else None


def _format_check_result(result: RunResult, file_path: Path, pre_commit: PreCommitConfig) -> str:
    output: str = templates.post_tool_use.render(result=result, file_path=file_path, pre_commit=pre_commit)
    return output.strip()


def evaluate(hook_input: PostToolUseInput, session: Session) -> HookOutput:
    if hook_input.tool_name not in FILE_MODIFYING_TOOLS:
        return HookOutput()

    try:
        parsed = parse_tool_input(hook_input.tool_name, hook_input.tool_input)
    except ValidationError as e:
        msg = f"Failed to parse {hook_input.tool_name} tool_input: {e}"
        logger.warning(msg)
        session.post_message(f"[tool_input_parsing] {msg}")
        parsed = None
    file_path = _get_file_path(parsed, hook_input.tool_input)
    if file_path is None or not file_path.exists():
        return HookOutput()

    search_dir = str(file_path.parent if file_path.is_file() else file_path)
    git_path = pygit2.discover_repository(search_dir)
    if git_path is None:
        return HookOutput()
    project_dir = Path(pygit2.Repository(git_path).workdir).resolve()

    pre_commit = session.profile.pre_commit
    if not pre_commit:
        return HookOutput()

    run_result = run_on_file(file_path, project_dir, auto_apply_hooks=pre_commit.auto_apply_hooks)

    for hook_id, hr in run_result.hooks.items():
        if isinstance(hr, HookAutoApplied):
            logger.info("hook %s auto-applied on %s (rerun exit %d)", hook_id, file_path.name, hr.rerun_exit_code)
        elif isinstance(hr, (HookWouldEdit, HookFailedNotApplied)):
            logger.info(
                "hook %s on %s (exit_code=%d):\n%s",
                hook_id,
                file_path.name,
                hr.exit_code,
                hr.output.decode(errors="replace"),
            )

    if not run_result.has_issues:
        return HookOutput()

    return HookOutput(
        hook_specific_output=PostToolUseHookSpecificOutput(
            additional_context=_format_check_result(run_result, file_path, pre_commit)
        )
    )
