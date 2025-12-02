"""DSPy metric using the existing LLM grader.

The grader is itself an LLM agent that compares found issues against ground truth.
This provides richer feedback than simple set intersection, including:
- Semantic matching (different wording, same issue)
- Partial credit for related findings
- Structured feedback for optimization

For DSPy optimization, we can use either:
1. Simple metric: Compute recall/precision from grader output (fast, for teleprompter)
2. Full metric: Run the LLM grader (slower, richer feedback, for final eval)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import dspy

if TYPE_CHECKING:
    from adgn.props.dspy_opt.examples import SpecimenExample
    from adgn.props.grader import GraderOutput
    from adgn.props.specimens.hydrated import HydratedSpecimen


def simple_recall_metric(
    example: "SpecimenExample",
    prediction: dspy.Prediction,
    trace: Any = None,
) -> float:
    """Simple recall metric using set intersection.

    Fast metric for DSPy optimization. Compares issue IDs directly.
    Use for teleprompter optimization; use grader_metric for final eval.

    Args:
        example: SpecimenExample with ground_truth_issues
        prediction: DSPy prediction with issues field
        trace: Optional trace (unused)

    Returns:
        Recall score (0-1)
    """
    # Extract expected issue IDs from ground truth
    expected_ids = {issue["id"] for issue in example.ground_truth_issues}
    if not expected_ids:
        return 1.0  # No issues expected = perfect recall

    # Extract found issue IDs from prediction
    found_issues = prediction.issues if hasattr(prediction, "issues") else []
    found_ids = {issue.get("id", "") for issue in found_issues if isinstance(issue, dict)}

    # Simple intersection
    matched = expected_ids & found_ids
    recall = len(matched) / len(expected_ids)

    return recall


def simple_f1_metric(
    example: "SpecimenExample",
    prediction: dspy.Prediction,
    trace: Any = None,
) -> float:
    """Simple F1 metric using set intersection.

    Balances recall and precision. Penalizes both missed issues and false positives.

    Args:
        example: SpecimenExample with ground_truth_issues and known_false_positives
        prediction: DSPy prediction with issues field
        trace: Optional trace (unused)

    Returns:
        F1 score (0-1)
    """
    expected_ids = {issue["id"] for issue in example.ground_truth_issues}
    known_fp_ids = {issue["id"] for issue in example.known_false_positives}

    found_issues = prediction.issues if hasattr(prediction, "issues") else []
    found_ids = {issue.get("id", "") for issue in found_issues if isinstance(issue, dict)}

    if not found_ids:
        return 0.0 if expected_ids else 1.0

    # True positives: found AND expected
    tp = len(expected_ids & found_ids)

    # False positives: found AND in known FP list
    fp = len(known_fp_ids & found_ids)

    # Precision: TP / (TP + FP) - only count known FPs, ignore novel findings
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0

    # Recall: TP / expected
    recall = tp / len(expected_ids) if expected_ids else 1.0

    # F1
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


async def grader_metric_async(
    example: "SpecimenExample",
    prediction: dspy.Prediction,
    hydrated_specimen: "HydratedSpecimen",
    *,
    verbose: bool = False,
) -> tuple[float, "GraderOutput"]:
    """Full LLM grader metric (async).

    Runs the actual grader agent for semantic matching and detailed feedback.
    Slower but more accurate than simple_recall_metric.

    Args:
        example: SpecimenExample with ground truth
        prediction: DSPy prediction with issues field
        hydrated_specimen: Hydrated specimen for grader context
        verbose: Enable verbose logging

    Returns:
        (recall_score, grader_output) tuple
    """
    from uuid import uuid4

    from adgn.openai_utils.client_factory import build_client
    from adgn.props.critic import CriticSubmitPayload, ReportedIssue
    from adgn.props.db import get_session
    from adgn.props.db.models import Critique
    from adgn.props.grader import GraderInput, run_grader
    from adgn.props.models.issue import Occurrence
    from adgn.props.rationale import Rationale

    # Convert prediction.issues to CriticSubmitPayload format
    found_issues = prediction.issues if hasattr(prediction, "issues") else []
    reported_issues = []

    for issue in found_issues:
        if not isinstance(issue, dict):
            continue
        reported_issues.append(
            ReportedIssue(
                id=issue.get("id", f"unknown-{uuid4().hex[:8]}"),
                rationale=Rationale(issue.get("rationale", "No rationale provided")),
                occurrences=[
                    Occurrence(
                        files={occ.get("file", "unknown"): occ.get("lines", [])},
                        notes=occ.get("notes"),
                    )
                    for occ in issue.get("occurrences", [])
                ],
            )
        )

    critique_payload = CriticSubmitPayload(issues=reported_issues)

    # Store critique in DB (grader expects it there)
    critique_id = uuid4()
    with get_session() as session:
        critique = Critique(
            id=critique_id,
            specimen_slug=example.slug,
            payload=critique_payload.model_dump(mode="json"),
        )
        session.add(critique)
        session.commit()

    # Run grader
    grader_input = GraderInput(
        specimen_slug=example.slug,
        critique_id=critique_id,
    )

    client = build_client()  # Uses default model
    grader_output, _run_id = await run_grader(
        input_data=grader_input,
        client=client,
        hydrated_specimen=hydrated_specimen,
        verbose=verbose,
    )

    return grader_output.recall, grader_output


def grader_metric(
    example: "SpecimenExample",
    prediction: dspy.Prediction,
    trace: Any = None,
) -> float:
    """Synchronous wrapper for grader_metric_async.

    Note: This requires the specimen to be hydrated. For DSPy optimization,
    prefer simple_recall_metric (faster) and use grader_metric for final eval.

    This is a placeholder - actual usage requires async context with hydrated specimen.
    """
    # For DSPy's teleprompter, we use the simple metric
    # The full grader is used in the optimization loop where we control the async context
    return simple_recall_metric(example, prediction, trace)


class GraderMetricWithContext:
    """Metric class that holds hydrated specimen context.

    Use this when you need the full LLM grader in DSPy evaluation.

    Example:
        async with registry.load_and_hydrate(slug) as hydrated:
            metric = GraderMetricWithContext(example, hydrated)
            score = await metric.evaluate(prediction)
    """

    def __init__(self, example: "SpecimenExample", hydrated: "HydratedSpecimen"):
        self.example = example
        self.hydrated = hydrated
        self._last_output: "GraderOutput | None" = None

    async def evaluate(self, prediction: dspy.Prediction) -> float:
        """Run full grader and return recall score."""
        recall, output = await grader_metric_async(
            self.example,
            prediction,
            self.hydrated,
        )
        self._last_output = output
        return recall

    @property
    def last_output(self) -> "GraderOutput | None":
        """Get the last grader output for detailed analysis."""
        return self._last_output
