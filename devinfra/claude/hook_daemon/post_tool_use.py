"""PostToolUse hook: lint-check files after Edit/Write tool calls.

Runs pre-commit on files that Claude Code just modified. Hooks listed in
the pre_commit.auto_apply_hooks config keep their changes on disk. All
other hooks' changes are reverted and issues are reported back to the agent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pygit2
from mako.template import Template

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.hook_config import HookConfig, PreCommitConfig
from devinfra.claude.hook_daemon.precommit_runner import (
    HookAutoApplied,
    HookFailedNotApplied,
    HookWouldEdit,
    RunResult,
    run_on_file,
)

logger = logging.getLogger(__name__)

FILE_MODIFYING_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _get_file_path(tool_input: dict[str, Any]) -> Path | None:
    file_path = tool_input.get("file_path")
    if file_path is None:
        return None
    return Path(file_path)


def _format_check_result(result: RunResult, file_path: Path, pre_commit: PreCommitConfig) -> str:
    template = Template((_TEMPLATES_DIR / "post_tool_use.mako").read_text())
    output: str = template.render(result=result, file_path=file_path, pre_commit=pre_commit)
    return output.strip()


def evaluate(hook_input: PostToolUseInput) -> PostToolUseOutput:
    if hook_input.tool_name not in FILE_MODIFYING_TOOLS:
        return PostToolUseOutput()

    file_path = _get_file_path(hook_input.tool_input)
    if file_path is None or not file_path.exists():
        return PostToolUseOutput()

    search_dir = str(file_path.parent if file_path.is_file() else file_path)
    git_path = pygit2.discover_repository(search_dir)
    if git_path is None:
        return PostToolUseOutput()
    project_dir = Path(pygit2.Repository(git_path).workdir).resolve()

    config = HookConfig.load_from_repo(project_dir)
    if not config or not config.pre_commit:
        return PostToolUseOutput()

    pre_commit = config.pre_commit
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
        return PostToolUseOutput()

    return PostToolUseOutput(
        hook_specific_output=PostToolUseHookSpecificOutput(
            additional_context=_format_check_result(run_result, file_path, pre_commit)
        )
    )
