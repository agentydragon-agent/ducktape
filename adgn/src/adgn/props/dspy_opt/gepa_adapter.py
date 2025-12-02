"""GEPA adapter for props critic optimization.

Integrates with gepa-ai/gepa to optimize the critic system prompt using
evolutionary search with rich feedback from execution traces and grader output.

Usage:
    from gepa import optimize
    from adgn.props.dspy_opt.gepa_adapter import CriticAdapter, load_datasets

    adapter = CriticAdapter(registry, client)
    trainset, valset = await load_datasets(registry)

    result = optimize(
        seed_candidate={"system_prompt": initial_prompt},
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_lm,
        max_metric_calls=100,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from uuid import UUID

import gepa

from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic import ALL_FILES_WITH_ISSUES, CriticInput, run_critic
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, Event, GraderRun as DBGraderRun
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.grader import GradeSubmitInput, GraderOutput, grade_critique_by_id
from adgn.props.specimens.hydrated import HydratedSpecimen
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.splits import Split

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class SpecimenInput:
    """Input for a single specimen evaluation."""

    slug: str
    target_files: list[str]
    ground_truth_issues: list[dict[str, Any]]
    known_false_positives: list[dict[str, Any]]


@dataclass
class CriticTrajectory:
    """Execution trajectory for a critic run."""

    specimen_slug: str
    transcript_id: UUID
    events: list[dict[str, Any]]  # Tool calls and outputs
    critique_payload: dict[str, Any]  # What the critic submitted


@dataclass
class CriticOutput:
    """Output from a critic evaluation."""

    specimen_slug: str
    issues_found: list[dict[str, Any]]
    grader_output: GradeSubmitInput | None
    recall: float


# =============================================================================
# Trace Formatting
# =============================================================================


def format_events_as_trace(events: list[dict[str, Any]], max_events: int = 50) -> str:
    """Format execution events as readable trace text."""
    lines = []
    tool_events = [e for e in events if e.get("type") in ("tool_call", "function_call_output")]

    if len(tool_events) > max_events:
        tool_events = tool_events[:max_events]
        lines.append(f"[Truncated to first {max_events} tool events]")

    for e in tool_events:
        if e.get("type") == "tool_call":
            name = e.get("payload", {}).get("name", "?")
            args = e.get("payload", {}).get("arguments", {})
            args_str = json.dumps(args)
            if len(args_str) > 200:
                args_str = args_str[:200] + "..."
            lines.append(f"CALL {name}({args_str})")
        elif e.get("type") == "function_call_output":
            output = str(e.get("payload", {}).get("output", ""))
            if len(output) > 300:
                output = output[:300] + "..."
            lines.append(f"  → {output}")

    return "\n".join(lines)


def format_grader_feedback(grade: GradeSubmitInput) -> str:
    """Format grader output as feedback text."""
    lines = []

    # Missed issues
    missed = [
        (tp_id, cov)
        for tp_id, cov in grade.canonical_tp_coverage.items()
        if not cov.covered_by
    ]
    if missed:
        lines.append("MISSED ISSUES:")
        for tp_id, cov in missed:
            lines.append(f"  - {tp_id}: {cov.rationale}")

    # False positives triggered
    fps_hit = [
        (fp_id, cov)
        for fp_id, cov in grade.canonical_fp_coverage.items()
        if cov.covered_by
    ]
    if fps_hit:
        lines.append("FALSE POSITIVES TRIGGERED:")
        for fp_id, cov in fps_hit:
            lines.append(f"  - {fp_id}: {cov.rationale}")

    lines.append(f"SUMMARY: {grade.summary}")

    return "\n".join(lines)


# =============================================================================
# GEPA Adapter
# =============================================================================


class CriticAdapter:
    """GEPA adapter for the props critic.

    Implements the GEPAAdapter protocol to allow GEPA to optimize
    the critic system prompt using your existing infrastructure.
    """

    def __init__(
        self,
        registry: SpecimenRegistry,
        client: OpenAIModelProto,
        verbose: bool = False,
    ):
        self.registry = registry
        self.client = client
        self.verbose = verbose

    def evaluate(
        self,
        batch: list[SpecimenInput],
        candidate: dict[str, str],
        capture_traces: bool = False,
    ) -> gepa.EvaluationBatch[CriticTrajectory, CriticOutput]:
        """Evaluate a prompt candidate on a batch of specimens.

        Args:
            batch: List of SpecimenInput to evaluate
            candidate: {"system_prompt": "..."} - the prompt to evaluate
            capture_traces: Whether to capture execution traces

        Returns:
            EvaluationBatch with outputs, scores, and optional trajectories
        """
        # Run async evaluation in sync context
        results = asyncio.run(self._evaluate_async(batch, candidate, capture_traces))

        outputs = [r["output"] for r in results]
        scores = [r["score"] for r in results]
        trajectories = [r["trajectory"] for r in results] if capture_traces else None

        return gepa.EvaluationBatch(
            outputs=outputs,
            scores=scores,
            trajectories=trajectories,
        )

    async def _evaluate_async(
        self,
        batch: list[SpecimenInput],
        candidate: dict[str, str],
        capture_traces: bool,
    ) -> list[dict[str, Any]]:
        """Async implementation of evaluate."""
        system_prompt = candidate["system_prompt"]
        prompt_sha256 = hash_and_upsert_prompt(system_prompt)

        results = []

        for specimen_input in batch:
            slug = specimen_input.slug

            try:
                # Run critic
                async with self.registry.load_and_hydrate(slug) as hydrated:
                    critic_input = CriticInput(
                        specimen_slug=slug,
                        files=ALL_FILES_WITH_ISSUES,
                        prompt_sha256=prompt_sha256,
                    )

                    critic_output, critic_run_id, critique_id = await run_critic(
                        input_data=critic_input,
                        client=self.client,
                        content_root=hydrated.content_root,
                        registry=self.registry,
                        mount_properties=True,
                        verbose=self.verbose,
                    )

                # Get transcript_id and events
                with get_session() as session:
                    critic_run = session.get(DBCriticRun, critic_run_id)
                    transcript_id = critic_run.transcript_id

                    events = []
                    if capture_traces:
                        event_rows = (
                            session.query(Event)
                            .filter(Event.transcript_id == transcript_id)
                            .order_by(Event.sequence_num)
                            .all()
                        )
                        events = [
                            {"seq": e.sequence_num, "type": e.event_type, "payload": e.payload}
                            for e in event_rows
                        ]

                # Grade
                grader_run_id = await grade_critique_by_id(
                    critique_id, self.client, verbose=self.verbose
                )

                # Get grader output
                with get_session() as session:
                    grader_run = session.get(DBGraderRun, grader_run_id)
                    grader_output = GraderOutput.model_validate(grader_run.output)

                output = CriticOutput(
                    specimen_slug=slug,
                    issues_found=critic_output.result.model_dump()["issues"],
                    grader_output=grader_output.grade,
                    recall=grader_output.recall,
                )

                trajectory = CriticTrajectory(
                    specimen_slug=slug,
                    transcript_id=transcript_id,
                    events=events,
                    critique_payload=critic_output.result.model_dump(),
                ) if capture_traces else None

                results.append({
                    "output": output,
                    "score": grader_output.recall,
                    "trajectory": trajectory,
                })

            except Exception as e:
                logger.error(f"Error evaluating {slug}: {e}")
                # GEPA contract: never raise, return zero score
                results.append({
                    "output": CriticOutput(
                        specimen_slug=slug,
                        issues_found=[],
                        grader_output=None,
                        recall=0.0,
                    ),
                    "score": 0.0,
                    "trajectory": None,
                })

        return results

    def make_reflective_dataset(
        self,
        candidate: dict[str, str],
        eval_batch: gepa.EvaluationBatch[CriticTrajectory, CriticOutput],
        components_to_update: list[str],
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        """Build reflective dataset for GEPA's teacher model.

        For each component being optimized, returns a list of examples
        showing what happened and what should be improved.
        """
        dataset: dict[str, list[dict[str, Any]]] = {}

        for component in components_to_update:
            if component != "system_prompt":
                continue  # Only optimize system_prompt

            examples = []
            for output, score, trajectory in zip(
                eval_batch.outputs,
                eval_batch.scores,
                eval_batch.trajectories or [None] * len(eval_batch.outputs),
            ):
                example = {
                    "component_name": "system_prompt",
                    "current_text": candidate["system_prompt"],
                    "score": score,
                    "specimen": output.specimen_slug,
                    "issues_found": output.issues_found,
                }

                # Add trace if available
                if trajectory:
                    example["trace"] = format_events_as_trace(trajectory.events)

                # Add grader feedback if available
                if output.grader_output:
                    example["grader_feedback"] = format_grader_feedback(output.grader_output)
                    example["grader_output"] = output.grader_output.model_dump()

                examples.append(example)

            dataset[component] = examples

        return dataset


# =============================================================================
# Dataset Loading
# =============================================================================


async def load_datasets(
    registry: SpecimenRegistry,
) -> tuple[list[SpecimenInput], list[SpecimenInput]]:
    """Load train and validation datasets for GEPA.

    Returns:
        (trainset, valset) tuple of SpecimenInput lists
    """
    train_slugs = registry.get_specimens_by_split(Split.TRAIN)
    valid_slugs = registry.get_specimens_by_split(Split.VALID)

    async def load_specimen(slug: str) -> SpecimenInput:
        async with registry.load_and_hydrate(slug) as hydrated:
            target_files = [str(f) for f in hydrated.files_with_issues()]

            # Use model_dump for Pydantic models
            ground_truth = [
                {
                    "id": issue_id,
                    "core": record.core.model_dump(),
                    "occurrences": [occ.model_dump() for occ in record.instances],
                }
                for issue_id, record in hydrated.issues.items()
            ]

            known_fps = [
                {
                    "id": fp_id,
                    "core": record.core.model_dump(),
                    "occurrences": [occ.model_dump() for occ in record.instances],
                }
                for fp_id, record in hydrated.false_positives.items()
            ]

            return SpecimenInput(
                slug=slug,
                target_files=target_files,
                ground_truth_issues=ground_truth,
                known_false_positives=known_fps,
            )

    trainset = [await load_specimen(slug) for slug in train_slugs]
    valset = [await load_specimen(slug) for slug in valid_slugs]

    return trainset, valset


# =============================================================================
# High-level API
# =============================================================================


async def optimize_with_gepa(
    initial_prompt: str,
    registry: SpecimenRegistry,
    client: OpenAIModelProto,
    *,
    reflection_model: str = "gpt-4o",
    max_metric_calls: int = 100,
    verbose: bool = False,
) -> tuple[str, Any]:
    """Optimize critic prompt using GEPA.

    Args:
        initial_prompt: Starting system prompt
        registry: SpecimenRegistry instance
        client: LLM client for critic/grader execution
        reflection_model: Model for GEPA's reflection
        max_metric_calls: Budget for evaluations
        verbose: Enable verbose logging

    Returns:
        (optimized_prompt, gepa_results) tuple
    """
    # Load datasets
    trainset, valset = await load_datasets(registry)

    # Create adapter
    adapter = CriticAdapter(registry, client, verbose=verbose)

    # Configure reflection LM
    reflection_lm = gepa.LM(model=reflection_model)

    # Run optimization
    result = gepa.optimize(
        seed_candidate={"system_prompt": initial_prompt},
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_lm,
        max_metric_calls=max_metric_calls,
        perfect_score=1.0,  # Perfect recall
    )

    optimized_prompt = result.best_candidate["system_prompt"]

    return optimized_prompt, result
