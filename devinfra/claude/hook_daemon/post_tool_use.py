"""PostToolUse hook: lint-check files after Edit/Write tool calls.

Runs pre-commit on files that Claude Code just modified, reports any
issues back to the agent (with a short diff of what pre-commit would
change), then restores the original file content so the agent can
fix issues itself.
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from devinfra.claude.claude_api.hooks.post_tool_use import (
    PostToolUseHookSpecificOutput,
    PostToolUseInput,
    PostToolUseOutput,
)
from devinfra.claude.hook_daemon.precommit_runner import RunResult, run_on_file

logger = logging.getLogger(__name__)

FILE_MODIFYING_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit"})

_MAX_ISSUES_SHOWN = 3
_MAX_DIFF_LINES = 20
_MAX_OUTPUT_CHARS = 500


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


def _make_short_diff(original: bytes, modified: bytes, filename: str) -> str:
    """Generate a truncated unified diff between original and modified content."""
    orig_lines = original.decode(errors="replace").splitlines(keepends=True)
    mod_lines = modified.decode(errors="replace").splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(orig_lines, mod_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}"))
    if not diff_lines:
        return ""
    if len(diff_lines) > _MAX_DIFF_LINES:
        diff_lines = diff_lines[:_MAX_DIFF_LINES]
        diff_lines.append(f"... (diff truncated, {len(diff_lines)} more lines)\n")
    return "".join(diff_lines).rstrip()


def _format_check_result(result: RunResult, file_path: Path) -> str:
    failed = result.failed_hooks
    noun = "hook" if len(failed) == 1 else "hooks"
    parts = [f"{len(failed)} {noun} failed on {file_path.name}:"]
    for hr in failed:
        status = "modified file" if hr.files_modified else f"exit {hr.exit_code}"
        parts.append(f"  {hr.hook_name} ({status})")
        output_text = hr.output.decode(errors="replace").strip()[:_MAX_OUTPUT_CHARS]
        if output_text:
            for line in output_text.splitlines()[:_MAX_ISSUES_SHOWN]:
                parts.append(f"    {line}")
    diff = _make_short_diff(result.original_content, result.modified_content, file_path.name)
    if diff:
        parts.append("Changes pre-commit would make:")
        parts.append(diff)
    parts.append(f"Run `pre-commit run --files {file_path}` to apply fixes.")
    return "\n".join(parts)


def evaluate(hook_input: PostToolUseInput) -> PostToolUseOutput:
    if hook_input.tool_name not in FILE_MODIFYING_TOOLS:
        return PostToolUseOutput()

    file_path = _get_file_path(hook_input.tool_input)
    if file_path is None or not file_path.exists():
        return PostToolUseOutput()

    project_dir = _find_git_root(file_path)
    if project_dir is None:
        return PostToolUseOutput()

    run_result = run_on_file(file_path, project_dir)

    for hr in run_result.hooks:
        if hr.passed:
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

    if run_result.all_passed:
        return PostToolUseOutput()

    return PostToolUseOutput(
        hook_specific_output=PostToolUseHookSpecificOutput(
            additional_context=_format_check_result(run_result, file_path)
        )
    )
