"""Linters for validating work tracking URLs and task metadata.

This module provides command-line linters that can be used standalone
or integrated with pre-commit hooks.
"""

from ducktape_llm_common.linters.base import BaseLinter, LintError, LintResult
from ducktape_llm_common.linters.check_task_metadata import MetadataLinter
from ducktape_llm_common.linters.check_work_urls import WorkURLLinter
from ducktape_llm_common.linters.claude_rules import ClaudeRulesLinter

__all__ = [
    "BaseLinter",
    "LintError",
    "LintResult",
    "WorkURLLinter",
    "MetadataLinter",
    "ClaudeRulesLinter",
]
