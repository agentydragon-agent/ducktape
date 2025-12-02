"""DSPy signatures for code review tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import dspy

if TYPE_CHECKING:
    from adgn.props.critic import ReportedIssue


class FindCodeIssues(dspy.Signature):
    """Find code quality issues in the specified files of a codebase.

    You have access to tools to read files, search code, and run commands
    (ruff, mypy, grep, ast analysis, etc.) in the workspace.

    For each issue found, provide:
    - A unique ID (kebab-case, descriptive)
    - A rationale explaining why this is problematic
    - The file(s) and line(s) where it occurs

    Focus on substantive issues: dead code, bugs, poor abstractions,
    missing error handling, unclear logic. Avoid trivial style nits.
    """

    specimen_slug: str = dspy.InputField(desc="Specimen identifier for tracking")
    target_files: list[str] = dspy.InputField(desc="Files to review (relative paths)")

    # Output is a list of issues - DSPy will handle structured output
    issues: list[dict] = dspy.OutputField(
        desc="List of issues found. Each has: id (str), rationale (str), "
        "occurrences (list of {file, lines, snippet})"
    )


class GradeCodeReview(dspy.Signature):
    """Grade a code review against ground truth issues.

    Compare the found issues against canonical true positives and known false positives.
    Compute recall (what fraction of canonical issues were found) and identify
    false positives and novel findings.
    """

    canonical_issues: list[dict] = dspy.InputField(desc="Ground truth issues that should be found")
    found_issues: list[dict] = dspy.InputField(desc="Issues reported by the critic")
    known_false_positives: list[dict] = dspy.InputField(desc="Known FPs to penalize if reported")

    recall: float = dspy.OutputField(desc="Fraction of canonical issues covered (0-1)")
    precision_estimate: float = dspy.OutputField(desc="Estimated precision based on known FPs")
    summary: str = dspy.OutputField(desc="Brief summary of coverage and gaps")
