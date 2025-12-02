"""Prompt optimization using DSPy GEPA with rich structured feedback.

DSPy GEPA optimizes prompt text using:
- Execution traces from MiniCodex (via events table)
- Structured grader output (full GradeSubmitInput, not just summary)
- Ground truth issues from specimens

Agent execution uses existing run_critic() and grade_critique_by_id().
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

import dspy

if TYPE_CHECKING:
    from adgn.openai_utils.model import OpenAIModelProto
    from adgn.props.grader import GradeSubmitInput
    from adgn.props.specimens.hydrated import HydratedSpecimen
    from adgn.props.specimens.registry import SpecimenRegistry

from adgn.props.splits import Split

logger = logging.getLogger(__name__)


# =============================================================================
# Trace Extraction
# =============================================================================


def fetch_execution_trace(transcript_id: UUID) -> list[dict[str, Any]]:
    """Fetch execution events for a transcript from DB.

    Returns list of events with: sequence_num, event_type, payload
    """
    from adgn.props.db import get_session
    from adgn.props.db.models import Event

    with get_session() as session:
        events = (
            session.query(Event)
            .filter(Event.transcript_id == transcript_id)
            .order_by(Event.sequence_num)
            .all()
        )
        return [
            {
                "seq": e.sequence_num,
                "type": e.event_type,
                "payload": e.payload,
            }
            for e in events
        ]


def format_trace_for_feedback(events: list[dict[str, Any]], max_events: int = 50) -> str:
    """Format execution trace as readable text for GEPA feedback.

    Focuses on tool calls and their outputs - the agent's behavior.
    """
    lines = []
    tool_events = [e for e in events if e["type"] in ("tool_call", "function_call_output")]

    # Truncate if too long
    if len(tool_events) > max_events:
        tool_events = tool_events[:max_events]
        lines.append(f"[Truncated to first {max_events} tool events]")

    for e in tool_events:
        if e["type"] == "tool_call":
            name = e["payload"].get("name", "?")
            args = e["payload"].get("arguments", {})
            # Truncate long arguments
            args_str = json.dumps(args, indent=None)
            if len(args_str) > 200:
                args_str = args_str[:200] + "..."
            lines.append(f"[{e['seq']}] CALL {name}({args_str})")
        elif e["type"] == "function_call_output":
            output = str(e["payload"].get("output", ""))
            if len(output) > 300:
                output = output[:300] + "..."
            lines.append(f"[{e['seq']}] → {output}")

    return "\n".join(lines)


# =============================================================================
# Structured Feedback
# =============================================================================


@dataclass
class RichEvalResult:
    """Evaluation result with full structured data for GEPA feedback."""

    specimen_slug: str
    critic_run_id: UUID
    critique_id: UUID
    grader_run_id: UUID
    transcript_id: UUID

    # Metrics
    recall: float

    # Full structured data (not just summaries)
    grader_output: "GradeSubmitInput"
    ground_truth_issues: list[dict[str, Any]]
    known_false_positives: list[dict[str, Any]]

    # Execution trace
    trace_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PromptEvaluation:
    """Full evaluation of a prompt on a set of specimens."""

    prompt_sha256: str
    results: list[RichEvalResult]

    @property
    def avg_recall(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.recall for r in self.results) / len(self.results)

    @property
    def failures(self) -> list[RichEvalResult]:
        """Results with recall < 1.0."""
        return [r for r in self.results if r.recall < 1.0]


def format_ground_truth(issues: list[dict[str, Any]]) -> str:
    """Format ground truth issues for feedback."""
    if not issues:
        return "No ground truth issues defined."

    lines = ["### Ground Truth Issues (what should be found):"]
    for issue in issues:
        issue_id = issue.get("id", "?")
        rationale = issue.get("rationale", "")
        occurrences = issue.get("occurrences", [])
        files = []
        for occ in occurrences:
            files.extend(occ.get("files", {}).keys())
        files_str = ", ".join(files[:3])
        if len(files) > 3:
            files_str += f" (+{len(files) - 3} more)"
        lines.append(f"- **{issue_id}**: {rationale[:100]}... (in {files_str})")

    return "\n".join(lines)


def format_grader_output(grade: "GradeSubmitInput") -> str:
    """Format full grader output for feedback."""
    lines = ["### Grader Analysis:"]

    # Coverage summary
    covered = sum(1 for cov in grade.canonical_tp_coverage.values() if cov.covered_by)
    total = len(grade.canonical_tp_coverage)
    lines.append(f"Covered {covered}/{total} canonical issues (recall={grade.recall:.2%})")

    # Missed issues (most important for optimization)
    missed = [
        (tp_id, cov)
        for tp_id, cov in grade.canonical_tp_coverage.items()
        if not cov.covered_by
    ]
    if missed:
        lines.append("\n**Missed Issues (CRITICAL - prompt must address these):**")
        for tp_id, cov in missed:
            lines.append(f"- {tp_id}: {cov.rationale}")

    # Partial coverage
    partial = [
        (tp_id, cov)
        for tp_id, cov in grade.canonical_tp_coverage.items()
        if cov.covered_by and cov.recall_credit < 1.0
    ]
    if partial:
        lines.append("\n**Partial Coverage (room for improvement):**")
        for tp_id, cov in partial:
            lines.append(f"- {tp_id} ({cov.recall_credit:.0%}): {cov.rationale}")

    # False positives hit
    fps_hit = [
        (fp_id, cov)
        for fp_id, cov in grade.canonical_fp_coverage.items()
        if cov.covered_by
    ]
    if fps_hit:
        lines.append("\n**False Positives Triggered (prompt should avoid):**")
        for fp_id, cov in fps_hit:
            lines.append(f"- {fp_id}: {cov.rationale}")

    # Summary
    lines.append(f"\n**Grader Summary:** {grade.summary}")

    return "\n".join(lines)


def format_rich_feedback(result: RichEvalResult) -> str:
    """Format a single evaluation result as rich feedback for GEPA."""
    sections = [
        f"# Specimen: {result.specimen_slug}",
        f"**Recall: {result.recall:.2%}**",
        "",
        format_ground_truth(result.ground_truth_issues),
        "",
        format_grader_output(result.grader_output),
        "",
        "### Execution Trace (what the agent did):",
        format_trace_for_feedback(result.trace_events),
    ]
    return "\n".join(sections)


# =============================================================================
# Evaluation
# =============================================================================


async def evaluate_prompt_on_specimen(
    prompt_sha256: str,
    hydrated: "HydratedSpecimen",
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    verbose: bool = False,
) -> RichEvalResult:
    """Evaluate a prompt on a single specimen, returning rich structured result."""
    from adgn.props.critic import ALL_FILES_WITH_ISSUES, CriticInput, run_critic
    from adgn.props.db import get_session
    from adgn.props.db.models import CriticRun as DBCriticRun, GraderRun as DBGraderRun
    from adgn.props.grader import GraderOutput, grade_critique_by_id

    slug = hydrated.slug

    # Run critic
    critic_input = CriticInput(
        specimen_slug=slug,
        files=ALL_FILES_WITH_ISSUES,
        prompt_sha256=prompt_sha256,
    )

    critic_output, critic_run_id, critique_id = await run_critic(
        input_data=critic_input,
        client=client,
        content_root=hydrated.content_root,
        registry=registry,
        mount_properties=True,
        verbose=verbose,
    )

    # Get transcript_id from critic run
    with get_session() as session:
        critic_run = session.get(DBCriticRun, critic_run_id)
        transcript_id = critic_run.transcript_id

    # Fetch execution trace
    trace_events = fetch_execution_trace(transcript_id)

    # Grade
    grader_run_id = await grade_critique_by_id(critique_id, client, verbose=verbose)

    # Fetch full grader output
    with get_session() as session:
        grader_run = session.get(DBGraderRun, grader_run_id)
        grader_output = GraderOutput.model_validate(grader_run.output)

    # Extract ground truth from specimen
    ground_truth_issues = [
        {
            "id": issue_id,
            "rationale": str(record.core.rationale),
            "occurrences": [
                {"files": {str(f): list(lines) for f, lines in occ.files.items()}}
                for occ in record.instances
            ],
        }
        for issue_id, record in hydrated.issues.items()
    ]

    known_fps = [
        {
            "id": fp_id,
            "rationale": str(record.core.rationale),
        }
        for fp_id, record in hydrated.false_positives.items()
    ]

    return RichEvalResult(
        specimen_slug=slug,
        critic_run_id=critic_run_id,
        critique_id=critique_id,
        grader_run_id=grader_run_id,
        transcript_id=transcript_id,
        recall=grader_output.recall,
        grader_output=grader_output.grade,
        ground_truth_issues=ground_truth_issues,
        known_false_positives=known_fps,
        trace_events=trace_events,
    )


async def evaluate_prompt_on_specimens(
    prompt_sha256: str,
    specimen_slugs: list[str],
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    verbose: bool = False,
) -> PromptEvaluation:
    """Evaluate a prompt on specimens using existing critic + grader."""
    results = []

    for slug in specimen_slugs:
        logger.info(f"Evaluating on {slug}...")

        async with registry.load_and_hydrate(slug) as hydrated:
            result = await evaluate_prompt_on_specimen(
                prompt_sha256=prompt_sha256,
                hydrated=hydrated,
                registry=registry,
                client=client,
                verbose=verbose,
            )
            results.append(result)
            logger.info(f"  {slug}: recall={result.recall:.2%}")

    return PromptEvaluation(prompt_sha256=prompt_sha256, results=results)


# =============================================================================
# GEPA Integration
# =============================================================================


class PromptImprover(dspy.Signature):
    """Improve a code review prompt based on detailed evaluation feedback.

    You receive:
    - The current system prompt
    - Rich feedback for each failed specimen including:
      - Ground truth issues (what should be found)
      - Grader analysis (what was missed, what was partially covered, what FPs triggered)
      - Execution trace (what the agent actually did - tool calls and outputs)

    Analyze the failures carefully. The execution trace shows HOW the agent behaved.
    The grader analysis shows WHAT it missed. The ground truth shows the TARGET.

    Propose specific, actionable improvements to the prompt.
    """

    current_prompt: str = dspy.InputField(desc="Current system prompt for code reviewer")
    feedback: str = dspy.InputField(
        desc="Rich structured feedback: ground truth issues, grader analysis, execution traces"
    )
    avg_recall: float = dspy.InputField(desc="Current average recall (0-1)")

    analysis: str = dspy.OutputField(
        desc="Analysis of what went wrong: patterns in missed issues, agent behavior problems"
    )
    improved_prompt: str = dspy.OutputField(
        desc="Improved system prompt. Add specific instructions to catch missed patterns. "
        "Reference concrete issue types from the feedback."
    )
    changes_made: str = dspy.OutputField(desc="Summary of changes and expected impact")


def format_failures_for_gepa(evaluation: PromptEvaluation) -> str:
    """Format all failure feedback for GEPA."""
    if not evaluation.failures:
        return "No failures - perfect recall on all specimens."

    sections = [format_rich_feedback(r) for r in evaluation.failures]
    return "\n\n---\n\n".join(sections)


async def improve_prompt_with_gepa(
    current_prompt: str,
    evaluation: PromptEvaluation,
) -> tuple[str, str, str]:
    """Use DSPy to propose an improved prompt with rich feedback.

    Returns:
        (improved_prompt, analysis, changes_summary) tuple
    """
    improver = dspy.ChainOfThought(PromptImprover)

    result = improver(
        current_prompt=current_prompt,
        feedback=format_failures_for_gepa(evaluation),
        avg_recall=evaluation.avg_recall,
    )

    return result.improved_prompt, result.analysis, result.changes_made


# =============================================================================
# Main Optimization Loop
# =============================================================================


async def optimize_critic_prompt(
    initial_prompt: str,
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    max_iterations: int = 5,
    target_recall: float = 0.95,
    verbose: bool = False,
) -> tuple[str, list[PromptEvaluation]]:
    """Optimize critic prompt using train specimens with GEPA-style feedback.

    Args:
        initial_prompt: Starting system prompt
        registry: SpecimenRegistry instance
        client: LLM client
        max_iterations: Max optimization iterations
        target_recall: Stop if avg recall exceeds this
        verbose: Enable verbose logging

    Returns:
        (best_prompt, evaluation_history) tuple
    """
    from adgn.props.db.prompts import hash_and_upsert_prompt

    # Get train specimens
    train_slugs = registry.get_specimens_by_split(Split.TRAIN)
    if not train_slugs:
        raise ValueError("No training specimens found")

    logger.info(f"Optimizing on {len(train_slugs)} train specimens")

    current_prompt = initial_prompt
    history: list[PromptEvaluation] = []
    best_prompt = initial_prompt
    best_recall = 0.0

    for iteration in range(max_iterations):
        logger.info(f"\n=== Iteration {iteration + 1}/{max_iterations} ===")

        # Store prompt in DB and get SHA
        prompt_sha256 = hash_and_upsert_prompt(current_prompt)

        # Evaluate current prompt
        evaluation = await evaluate_prompt_on_specimens(
            prompt_sha256=prompt_sha256,
            specimen_slugs=train_slugs,
            registry=registry,
            client=client,
            verbose=verbose,
        )
        history.append(evaluation)

        logger.info(f"Avg recall: {evaluation.avg_recall:.2%}")

        # Track best
        if evaluation.avg_recall > best_recall:
            best_recall = evaluation.avg_recall
            best_prompt = current_prompt

        # Check convergence
        if evaluation.avg_recall >= target_recall:
            logger.info(f"Target recall {target_recall:.2%} achieved!")
            break

        if not evaluation.failures:
            logger.info("No failures to improve on")
            break

        # Generate improved prompt with rich feedback
        logger.info("Generating improved prompt...")
        current_prompt, analysis, changes = await improve_prompt_with_gepa(
            current_prompt, evaluation
        )
        logger.info(f"Analysis: {analysis[:200]}...")
        logger.info(f"Changes: {changes}")

    return best_prompt, history


async def evaluate_on_validation(
    prompt: str,
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    verbose: bool = False,
) -> PromptEvaluation:
    """Evaluate optimized prompt on validation set."""
    from adgn.props.db.prompts import hash_and_upsert_prompt

    valid_slugs = registry.get_specimens_by_split(Split.VALID)
    if not valid_slugs:
        raise ValueError("No validation specimens found")

    prompt_sha256 = hash_and_upsert_prompt(prompt)

    return await evaluate_prompt_on_specimens(
        prompt_sha256=prompt_sha256,
        specimen_slugs=valid_slugs,
        registry=registry,
        client=client,
        verbose=verbose,
    )
