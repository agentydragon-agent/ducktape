"""Per-file recall evaluation.

For each file in a specimen that contains issues, run the critic on just that file
and measure which issues it detects. Aggregates to per-issue and specimen-level metrics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.handler import BaseHandler
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.agent_runners import CostTrackingHandler, run_critic_agent, run_grader_agent
from adgn.props.critic import CriticSubmitPayload
from adgn.props.grader import GradeSubmitPayload
from adgn.props.lint_issue import extract_canonical_issue_ids
from adgn.props.prompts.util import render_prompt_template
from adgn.props.specimens.registry import IssueRecord, SpecimenRegistry

logger = logging.getLogger(__name__)


class PerFileRunResult(BaseModel):
    """Result of running critic on a single file."""

    file_path: str = Field(description="Relative path of the file reviewed")
    issues_in_file: list[str] = Field(description="Issue IDs that have at least one occurrence in this file")
    critique: CriticSubmitPayload | None = Field(
        default=None, description="Critique payload from agent (None if failed)"
    )
    grade: GradeSubmitPayload | None = Field(
        default=None,
        description="Grading result comparing critique to canonical issues in this file (None if critique failed)",
    )
    detected_issue_ids: list[str] = Field(
        default_factory=list, description="Issue IDs that were successfully detected (matched as TP by grader)"
    )
    critique_dir: str = Field(description="Directory containing critique artifacts (transcript, unknowns, etc)")
    cost: float = Field(description="Total cost for this file (critic + grader)")

    model_config = ConfigDict(extra="forbid")


class PerIssueResult(BaseModel):
    """Aggregated result for a single issue across all files it touches."""

    issue_id: str
    files_containing_issue: list[str] = Field(description="Files where this issue has at least one occurrence")
    files_that_detected: list[str] = Field(
        default_factory=list, description="Files where the per-file critic run successfully detected this issue"
    )
    detected: bool = Field(description="True if issue was detected in at least one of its files")

    model_config = ConfigDict(extra="forbid")


class PerFileEvalMetrics(BaseModel):
    """Aggregate metrics for per-file evaluation.

    NOTE: Precision metrics may underestimate true precision because specimen labeling
    is not guaranteed to be comprehensive. Files may contain real issues that weren't
    labeled in the specimen. Recall is more trustworthy.
    """

    total_issues: int = Field(description="Total issues in specimen")
    detected_issues: int = Field(description="Issues detected in at least one of their files")
    recall: float = Field(description="detected_issues / total_issues", ge=0.0, le=1.0)

    total_files_reviewed: int = Field(description="Number of files that were reviewed")
    total_file_runs: int = Field(description="Total critic runs (one per file)")

    # Per-file-run aggregate metrics (averaged)
    # CAVEAT: Precision may be artificially low due to incomplete labeling
    avg_file_precision: float | None = Field(
        default=None,
        description="Average precision across per-file runs (may underestimate - see class docstring)",
        ge=0.0,
        le=1.0,
    )
    avg_file_recall: float | None = Field(
        default=None, description="Average recall across all per-file runs (where grading succeeded)", ge=0.0, le=1.0
    )

    model_config = ConfigDict(extra="forbid")


class PerFileEvalResult(BaseModel):
    """Complete per-file evaluation result for a specimen."""

    specimen: str
    metrics: PerFileEvalMetrics
    per_file_runs: list[PerFileRunResult] = Field(description="Results for each file reviewed")
    per_issue_results: list[PerIssueResult] = Field(description="Aggregated detection results per issue")
    eval_dir: str = Field(description="Root directory containing all eval artifacts")

    model_config = ConfigDict(extra="forbid")


@dataclass
class FileIssuesIndex:
    """Index mapping files to issues that touch them (single-file issues only)."""

    file_to_issues: dict[str, list[str]]  # file path -> issue IDs
    issue_to_files: dict[str, list[str]]  # issue ID -> file paths (all single-element lists)
    multi_file_issues: dict[str, list[str]]  # issue ID -> file paths (for issues spanning multiple files)


def build_file_issues_index(issues: dict[str, IssueRecord]) -> FileIssuesIndex:
    """Build bidirectional index of which files contain which issues.

    Only includes single-file issues in the main index. Multi-file issues are tracked separately.
    """
    file_to_issues: dict[str, list[str]] = {}
    issue_to_files: dict[str, list[str]] = {}
    multi_file_issues: dict[str, list[str]] = {}

    for issue_id, issue_rec in issues.items():
        files_for_issue: set[str] = set()
        for occ in issue_rec.instances:
            for file_path in occ.files:
                files_for_issue.add(file_path)

        files_list = sorted(files_for_issue)

        # Only index single-file issues in the main index
        if len(files_list) == 1:
            file_path = files_list[0]
            file_to_issues.setdefault(file_path, []).append(issue_id)
            issue_to_files[issue_id] = files_list
        else:
            # Track multi-file issues separately
            multi_file_issues[issue_id] = files_list

    return FileIssuesIndex(
        file_to_issues={k: sorted(set(v)) for k, v in file_to_issues.items()},
        issue_to_files=issue_to_files,
        multi_file_issues=multi_file_issues,
    )


# Helper functions now use shared runners from agent_runners.py


async def run_per_file_eval(
    specimen: str,
    *,
    system_prompt: str,
    client: OpenAIModelProto,
    out_dir: Path,
    gitconfig: Path | None = None,
    file_filter: str | None = None,
    verbose: bool = False,
) -> PerFileEvalResult:
    """Run per-file recall evaluation on a specimen.

    For each file containing issues:
    1. Run critic on just that file
    2. Grade critique against issues in that file
    3. Record which issues were detected

    Args:
        specimen: Specimen slug (e.g., "ducktape/2025-11-20-adgn")
        system_prompt: System prompt for critic agent (defines agent behavior)
        client: OpenAI-compatible client
        out_dir: Root directory for eval artifacts
        gitconfig: Optional path to gitconfig for private repo access
        file_filter: Optional file path to evaluate (if None, evaluates all files)
        verbose: If True, display agent events on stdout

    Returns structured results with per-file and per-issue breakdowns.
    """
    rec = SpecimenRegistry.load_strict(specimen)
    index = build_file_issues_index(rec.issues)

    # Sort files for deterministic ordering
    files_to_review = sorted(index.file_to_issues.keys())

    # Apply file filter if specified
    if file_filter is not None:
        if file_filter not in files_to_review:
            raise ValueError(
                f"File '{file_filter}' not found in specimen or has no single-file issues. "
                f"Available files: {', '.join(files_to_review)}"
            )
        files_to_review = [file_filter]

    async def process_one_file(file_path: str) -> PerFileRunResult:
        """Process a single file: run critic and grader, return results."""
        issues_in_file = index.file_to_issues[file_path]

        # Run critic on this single file
        file_run_dir = out_dir / "files" / file_path.replace("/", "__")
        file_run_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Running critic on {file_path} (issues: {', '.join(issues_in_file)})")

        # Build user prompt targeting just this file
        scope_text = f"Review the following file:\n- {file_path}"
        user_prompt = render_prompt_template("critic_user_prompt.j2.md", scope_text=scope_text)

        # Set up cost tracking and optional verbose display
        cost_tracker = CostTrackingHandler()
        handlers_list: list[BaseHandler] = [cost_tracker]
        if verbose:
            handlers_list.insert(0, DisplayEventsHandler(max_lines=10, prefix="  [EVAL] "))
        extra_handlers = tuple(handlers_list)

        critique = await run_critic_agent(
            specimen_rec=rec,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            client=client,
            transcript_dir=file_run_dir / "critic",
            mount_properties=False,
            gitconfig=gitconfig,
            extra_handlers=extra_handlers,
        )

        critic_cost = cost_tracker.total_cost  # Capture critic cost before grader resets
        logger.info(f"Grading critique for {file_path}")

        # Filter issues to only those in this file
        filtered_issues = {k: v for k, v in rec.issues.items() if k in issues_in_file}

        # Reset cost tracker for grader
        cost_tracker.total_cost = 0.0

        grade = await run_grader_agent(
            specimen_rec=rec,
            critique=critique,
            canonical_issues=filtered_issues,
            known_fps=None,  # TODO: Consider adding FP filtering for per-file eval
            scope_text=f"File: {file_path}",
            client=client,
            transcript_dir=file_run_dir / "grader",
            gitconfig=gitconfig,
            extra_handlers=extra_handlers,
        )

        grader_cost = cost_tracker.total_cost
        # Total cost for this file (critic + grader)
        total_file_cost = critic_cost + grader_cost

        # Extract canon_tp_ IDs and strip prefix to get original issue IDs
        detected_ids = extract_canonical_issue_ids(grade.true_positive_ids)

        return PerFileRunResult(
            file_path=file_path,
            issues_in_file=issues_in_file,
            critique=critique,
            grade=grade,
            detected_issue_ids=detected_ids,
            critique_dir=str(file_run_dir),
            cost=total_file_cost,
        )

    # Run all files in parallel
    results = await asyncio.gather(*[process_one_file(fp) for fp in files_to_review], return_exceptions=True)

    # Check for exceptions and collect successful results
    per_file_runs: list[PerFileRunResult] = []
    errors: list[tuple[str, BaseException]] = []

    for file_path, result in zip(files_to_review, results, strict=True):
        if isinstance(result, BaseException):
            errors.append((file_path, result))
            logger.error(f"Failed to process {file_path}: {result}")
        else:
            per_file_runs.append(result)

    # If any files failed, raise an exception with details
    if errors:
        error_summary = "\n".join(f"  - {fp}: {type(e).__name__}: {e}" for fp, e in errors)
        raise RuntimeError(f"Failed to process {len(errors)} file(s):\n{error_summary}")

    # Aggregate per-issue results (only for issues in reviewed files)
    per_issue_results: list[PerIssueResult] = []
    reviewed_files_set = set(files_to_review)

    for issue_id, files_containing in index.issue_to_files.items():
        # Skip issues not in any reviewed file
        if not any(f in reviewed_files_set for f in files_containing):
            continue

        # Find which files detected this issue
        files_that_detected = [run.file_path for run in per_file_runs if issue_id in run.detected_issue_ids]

        per_issue_results.append(
            PerIssueResult(
                issue_id=issue_id,
                files_containing_issue=files_containing,
                files_that_detected=files_that_detected,
                detected=len(files_that_detected) > 0,
            )
        )

    # Compute aggregate metrics
    total_issues = len(per_issue_results)
    detected_issues = sum(1 for r in per_issue_results if r.detected)
    recall = detected_issues / total_issues if total_issues > 0 else 0.0

    # Average per-file metrics
    file_precisions = [run.grade.metrics.precision for run in per_file_runs if run.grade is not None]
    file_recalls = [run.grade.metrics.recall for run in per_file_runs if run.grade is not None]

    metrics = PerFileEvalMetrics(
        total_issues=total_issues,
        detected_issues=detected_issues,
        recall=recall,
        total_files_reviewed=len(files_to_review),
        total_file_runs=len(per_file_runs),
        avg_file_precision=sum(file_precisions) / len(file_precisions) if file_precisions else None,
        avg_file_recall=sum(file_recalls) / len(file_recalls) if file_recalls else None,
    )

    return PerFileEvalResult(
        specimen=specimen,
        metrics=metrics,
        per_file_runs=per_file_runs,
        per_issue_results=per_issue_results,
        eval_dir=str(out_dir),
    )
