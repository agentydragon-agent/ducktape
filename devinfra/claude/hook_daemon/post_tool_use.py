"""PostToolUse hook: lint-check files after Edit/Write tool calls.

Runs pre-commit on files that Claude Code just modified. Hooks listed in
the pre_commit.auto_apply_hooks config keep their changes on disk. All
other hooks' changes are reverted and issues are reported back to the agent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mako.template import Template

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.hook_config import HookConfig
from devinfra.claude.hook_daemon.precommit_runner import RunResult, run_on_file

logger = logging.getLogger(__name__)

FILE_MODIFYING_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


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


def _format_check_result(
    result: RunResult, file_path: Path, *, show_report_diffs: bool = False, show_hook_output: bool = False
) -> str:
    template = Template((_TEMPLATES_DIR / "post_tool_use.mako").read_text())
    output: str = template.render(
        auto_applied=result.auto_applied_results,
        failed=result.failed_hooks,
        diff_lines=result.report_only_diff if show_report_diffs else [],
        show_hook_output=show_hook_output,
        file_name=file_path.name,
        file_path=file_path,
    )
    return output.strip()


def evaluate(hook_input: PostToolUseInput) -> PostToolUseOutput:
    if hook_input.tool_name not in FILE_MODIFYING_TOOLS:
        return PostToolUseOutput()

    file_path = _get_file_path(hook_input.tool_input)
    if file_path is None or not file_path.exists():
        return PostToolUseOutput()

    project_dir = _find_git_root(file_path)
    if project_dir is None:
        return PostToolUseOutput()

    config = HookConfig.load_from_repo(project_dir)
    pre_commit = config.pre_commit if config else None
    auto_apply_hooks = frozenset(pre_commit.auto_apply_hooks) if pre_commit else frozenset()
    show_report_diffs = pre_commit.show_report_diffs if pre_commit else False
    show_hook_output = pre_commit.show_hook_output if pre_commit else False

    run_result = run_on_file(file_path, project_dir, auto_apply_hooks=auto_apply_hooks)

    for hr in run_result.hooks:
        if hr.auto_applied:
            logger.info("hook %s auto-applied on %s", hr.hook_name, file_path.name)
        elif hr.passed:
            logger.debug("hook %s passed on %s", hr.hook_name, file_path.name)
        else:
            logger.info(
                "hook %s failed on %s (exit_code=%d, files_modified=%s):\n%s",
                hr.hook_name,
                file_path.name,
                hr.exit_code,
                hr.files_modified,
                hr.output.decode(errors="replace"),
            )

    if run_result.all_passed and not run_result.auto_applied_results:
        return PostToolUseOutput()

    return PostToolUseOutput(
        hook_specific_output=PostToolUseHookSpecificOutput(
            additional_context=_format_check_result(
                run_result, file_path, show_report_diffs=show_report_diffs, show_hook_output=show_hook_output
            )
        )
    )
