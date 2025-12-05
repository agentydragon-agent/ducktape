"""GEPA adapter for props critic optimization.

Integrates with gepa-ai/gepa to optimize the critic system prompt using
evolutionary search with rich feedback from execution traces and grader output.

Usage:
    from gepa import optimize
    from adgn.props.gepa.gepa_adapter import CriticAdapter, load_datasets

    adapter = CriticAdapter(hydrator, registry, critic_client, grader_client)
    trainset, valset = await load_datasets()  # Loads from database

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
from collections.abc import Mapping, Sequence
import concurrent.futures
from dataclasses import dataclass
from itertools import chain
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from adgn.agent.events import EventType
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput, CriticSubmitPayload, ReportedIssue
from adgn.props.db import get_session
from adgn.props.db.adapters import orm_to_wrapper_fps, orm_to_wrapper_tps
from adgn.props.db.models import CriticRun as DBCriticRun, Event, GraderRun as DBGraderRun, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.grader.models import GraderOutput, GradeSubmitInput
from adgn.props.ids import FalsePositiveID, SnapshotSlug, TruePositiveID
from adgn.props.models.critic_scopes import ALL_FILES_WITH_ISSUES
from adgn.props.snapshot_hydrator import SnapshotHydrator
from adgn.props.snapshot_registry import KnownFalsePositive, SnapshotRegistry, TruePositiveIssue
from adgn.props.splits import Split
import gepa
from gepa.core.result import GEPAResult

logger = logging.getLogger(__name__)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class SnapshotInput:
    """Input for a single snapshot evaluation.

    TODO: Rename to something clearer (e.g., EvaluationContext, GraderInput, CriticEvaluationInput).
    Current name is ambiguous with CriticInput. This represents the evaluation context for
    GEPA optimization: which files to review + ground truth for grading.
    """

    slug: SnapshotSlug
    target_files: set[Path]
    known_true_positives: dict[TruePositiveID, TruePositiveIssue]
    known_false_positives: dict[FalsePositiveID, KnownFalsePositive]


@dataclass
class CriticTrajectory:
    """Execution trajectory for a critic run."""

    snapshot_slug: SnapshotSlug
    transcript_id: UUID
    events: list[EventType]
    critique_payload: CriticSubmitPayload


@dataclass
class CriticOutput:
    """Output from a critic evaluation."""

    snapshot_slug: SnapshotSlug
    issues_found: list[ReportedIssue]
    grader_output: GradeSubmitInput | None
    recall: float


@dataclass
class EvaluationResult:
    """Result from evaluating a single specimen."""

    output: CriticOutput
    score: float
    trajectory: CriticTrajectory | None


class ReflectionExample(BaseModel):
    """Example for GEPA's reflection dataset."""

    component_name: str
    current_text: str
    score: float
    specimen: str
    issues_found: list[ReportedIssue]
    events: list[EventType]
    critique_payload: CriticSubmitPayload
    grader_output: GradeSubmitInput | None = None


# =============================================================================
# Trace Extraction
# =============================================================================


def serialize_events(events: list[EventType], max_events: int = 50) -> list[dict[str, Any]]:
    """Serialize all events as payloads for reflection dataset."""
    if len(events) > max_events:
        events = events[:max_events]
    return [e.model_dump() for e in events]


# =============================================================================
# GEPA Adapter
# =============================================================================


class CriticAdapter(gepa.GEPAAdapter[SnapshotInput, CriticTrajectory, CriticOutput]):
    """GEPA adapter for the props critic.

    Implements the GEPAAdapter protocol to allow GEPA to optimize
    the critic system prompt using your existing infrastructure.
    """

    def __init__(
        self,
        hydrator: SnapshotHydrator,
        registry: SnapshotRegistry,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        verbose: bool = False,
    ):
        self.hydrator = hydrator
        self.registry = registry
        self.critic_client = critic_client
        self.grader_client = grader_client
        self.verbose = verbose
        # Use GEPA's default proposal implementation
        self.propose_new_texts = None

    def evaluate(
        self, batch: list[SnapshotInput], candidate: dict[str, str], capture_traces: bool = False
    ) -> gepa.EvaluationBatch[CriticTrajectory, CriticOutput]:
        """Evaluate a prompt candidate on a batch of specimens.

        Args:
            batch: List of SnapshotInput to evaluate
            candidate: {"system_prompt": "..."} - the prompt to evaluate
            capture_traces: Whether to capture execution traces

        Returns:
            EvaluationBatch with outputs, scores, and optional trajectories
        """

        # GEPA's evaluate() is synchronous, but our implementation is async
        # Run async code in a new thread with its own event loop to avoid conflicts
        def run_in_new_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._evaluate_async(batch, candidate, capture_traces))
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_new_loop)
            results = future.result()

        outputs = [r.output for r in results]
        scores = [r.score for r in results]

        trajectories: list[CriticTrajectory] | None
        if capture_traces:
            # When capture_traces=True, trajectories must be present
            trajectories_with_nones = [r.trajectory for r in results]
            assert all(t is not None for t in trajectories_with_nones), (
                "Trajectories must be present when capture_traces=True"
            )
            trajectories = [t for t in trajectories_with_nones if t is not None]
        else:
            trajectories = None

        return gepa.EvaluationBatch(outputs=outputs, scores=scores, trajectories=trajectories)

    async def _evaluate_one_specimen(
        self, specimen_input: SnapshotInput, prompt_sha256: str, capture_traces: bool
    ) -> EvaluationResult:
        """Evaluate a single specimen (for parallel execution)."""
        slug = specimen_input.slug

        # Run critic
        async with self.hydrator.hydrate(slug) as hydrated:
            critic_input = CriticInput(snapshot_slug=slug, files=ALL_FILES_WITH_ISSUES, prompt_sha256=prompt_sha256)

            critic_output, critic_run_id, critique_id = await run_critic(
                input_data=critic_input,
                client=self.critic_client,
                content_root=hydrated.content_root,
                registry=self.registry,
                mount_properties=True,
                verbose=self.verbose,
            )

        # Get transcript_id and events
        with get_session() as session:
            critic_run = session.get(DBCriticRun, critic_run_id)
            assert critic_run is not None, f"CriticRun {critic_run_id} not found"
            transcript_id = critic_run.transcript_id

            events: list[EventType] = []
            if capture_traces:
                event_rows = (
                    session.query(Event).filter(Event.transcript_id == transcript_id).order_by(Event.sequence_num).all()
                )
                # Payload is already a typed EventType thanks to PydanticColumn
                events = [e.payload for e in event_rows]

        # Grade and fetch output in single session
        with get_session() as session:
            grader_run_id = await grade_critique_by_id(session, critique_id, self.grader_client, verbose=self.verbose)
            grader_run = session.get(DBGraderRun, grader_run_id)
            assert grader_run is not None, f"GraderRun {grader_run_id} not found"
            grader_output = GraderOutput.model_validate(grader_run.output)

        output = CriticOutput(
            snapshot_slug=slug,
            issues_found=critic_output.result.issues,
            grader_output=grader_output.grade,
            recall=grader_output.recall,
        )

        trajectory = (
            CriticTrajectory(
                snapshot_slug=slug, transcript_id=transcript_id, events=events, critique_payload=critic_output.result
            )
            if capture_traces
            else None
        )

        return EvaluationResult(output=output, score=grader_output.recall, trajectory=trajectory)

    async def _evaluate_async(
        self, batch: list[SnapshotInput], candidate: dict[str, str], capture_traces: bool
    ) -> list[EvaluationResult]:
        """Async implementation of evaluate - runs specimens in parallel."""
        system_prompt = candidate["system_prompt"]
        prompt_sha256 = hash_and_upsert_prompt(system_prompt)

        # Run all specimens in parallel
        tasks = [self._evaluate_one_specimen(specimen_input, prompt_sha256, capture_traces) for specimen_input in batch]
        results = await asyncio.gather(*tasks)

        return list(results)

    def make_reflective_dataset(
        self,
        candidate: dict[str, str],
        eval_batch: gepa.EvaluationBatch[CriticTrajectory, CriticOutput],
        components_to_update: list[str],
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        """Build reflective dataset for GEPA's teacher model.

        For each component being optimized, returns a list of examples
        showing what happened and what should be improved.

        Currently only supports optimizing 'system_prompt' component.
        """
        # Validate that we only received supported components
        unsupported = [c for c in components_to_update if c != "system_prompt"]
        if unsupported:
            raise ValueError(
                f"Unsupported components for optimization: {unsupported}. Only 'system_prompt' is supported."
            )

        # GEPA always calls this with capture_traces=True, so trajectories must exist
        assert eval_batch.trajectories is not None, "make_reflective_dataset requires trajectories"

        # Since we only support system_prompt component, process it directly
        examples: list[Mapping[str, Any]] = []
        for output, score, trajectory in zip(
            eval_batch.outputs, eval_batch.scores, eval_batch.trajectories, strict=True
        ):
            example = ReflectionExample(
                component_name="system_prompt",
                current_text=candidate["system_prompt"],
                score=score,
                specimen=output.snapshot_slug,
                issues_found=output.issues_found,
                events=trajectory.events,
                critique_payload=trajectory.critique_payload,
                grader_output=output.grader_output,
            )

            examples.append(example.model_dump())

        return {"system_prompt": examples}


# =============================================================================
# Dataset Loading
# =============================================================================


def _build_snapshot_inputs_from_snapshot(snapshot: Snapshot) -> list[SnapshotInput]:
    """Build SnapshotInputs directly from Snapshot ORM object using critic scopes.

    Requires critic scopes to be defined in database (sync validation ensures this).

    Args:
        snapshot: Snapshot ORM object with relationships loaded

    Returns:
        List of SnapshotInput objects (one per critic scope)

    Raises:
        ValueError: If snapshot has no critic scopes (should be caught during sync)
    """
    if not snapshot.critic_scopes:
        raise ValueError(f"Snapshot {snapshot.slug} has no critic scopes - sync validation should have caught this")

    # Convert ORM to wrapper types (for grader)
    tps_list = orm_to_wrapper_tps(snapshot.true_positives)
    fps_list = orm_to_wrapper_fps(snapshot.false_positives)
    tps = {tp.id: tp for tp in tps_list}
    fps = {fp.id: fp for fp in fps_list}

    # Collect all files with issues for "all" sentinel resolution
    all_files = snapshot.files_with_issues()

    inputs: list[SnapshotInput] = []

    # Generate one SnapshotInput per critic scope
    for scope_db in snapshot.critic_scopes:
        # Resolve "all" sentinel to actual file set
        targeted_files = all_files if scope_db.files == ALL_FILES_WITH_ISSUES else scope_db.files  # type: ignore[assignment]

        snapshot_input = SnapshotInput(
            slug=snapshot.slug, target_files=set(targeted_files), known_true_positives=tps, known_false_positives=fps
        )
        inputs.append(snapshot_input)

    return inputs


async def load_datasets() -> tuple[list[SnapshotInput], list[SnapshotInput]]:
    """Load train and validation datasets for GEPA from database.

    Builds SnapshotInputs directly from Snapshot ORM objects using critic scopes.
    Each critic scope becomes one training example. All data comes from database.

    Returns:
        (trainset, valset) tuple of SnapshotInput lists

    Raises:
        ValueError: If any snapshot has no critic scopes (should be caught during sync)
    """
    logger.info("Loading training examples from critic_scopes database")

    with get_session() as session:
        train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN).all()
        valid_snapshots = session.query(Snapshot).filter_by(split=Split.VALID).all()

        # Build SnapshotInputs directly from ORM (one per critic scope)
        # Must do this inside session context to access lazy-loaded relationships
        trainset = list(chain.from_iterable(_build_snapshot_inputs_from_snapshot(s) for s in train_snapshots))
        valset = list(chain.from_iterable(_build_snapshot_inputs_from_snapshot(s) for s in valid_snapshots))

    logger.info(f"Loaded {len(trainset)} training examples, {len(valset)} validation examples")
    logger.info(f"From {len(train_snapshots)} train snapshots, {len(valid_snapshots)} valid snapshots")

    return trainset, valset


# =============================================================================
# High-level API
# =============================================================================


async def optimize_with_gepa(
    initial_prompt: str,
    hydrator: SnapshotHydrator,
    registry: SnapshotRegistry,
    critic_client: OpenAIModelProto,
    grader_client: OpenAIModelProto,
    *,
    reflection_model: str,
    max_metric_calls: int = 100,
    verbose: bool = False,
) -> tuple[str, GEPAResult[CriticOutput, Any]]:
    """Optimize critic prompt using GEPA.

    Uses critic scopes from database to generate training examples (one per scope).
    Requires all snapshots to have critic scopes defined (enforced by sync validation).

    Args:
        initial_prompt: Starting system prompt
        hydrator: SnapshotHydrator instance for source code hydration
        registry: SnapshotRegistry instance
        critic_client: LLM client for critic execution
        grader_client: LLM client for grader execution
        reflection_model: Model for GEPA's reflection
        max_metric_calls: Budget for evaluations
        verbose: Enable verbose logging

    Returns:
        (optimized_prompt, gepa_results) tuple

    Raises:
        ValueError: If any snapshot has no critic scopes
    """
    logger.info("Starting GEPA optimization")
    logger.info(f"Reflection model: {reflection_model}")
    logger.info(f"Max metric calls: {max_metric_calls}")
    logger.info(f"Initial prompt length: {len(initial_prompt)} chars")

    # Load datasets (always uses critic scopes from database)
    logger.info("Loading datasets...")
    trainset, valset = await load_datasets()
    logger.info(f"Loaded {len(trainset)} training examples, {len(valset)} validation examples")

    # Create adapter
    logger.info("Creating CriticAdapter")
    adapter = CriticAdapter(hydrator, registry, critic_client, grader_client, verbose=verbose)

    # Run optimization (reflection_lm accepts model string directly)
    logger.info("Starting GEPA evolutionary search...")
    result: GEPAResult[CriticOutput, Any] = gepa.optimize(
        seed_candidate={"system_prompt": initial_prompt},
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_model,
        max_metric_calls=max_metric_calls,
        perfect_score=1.0,  # Perfect recall
    )

    optimized_prompt = result.best_candidate["system_prompt"]
    best_score = result.val_aggregate_scores[result.best_idx]
    metric_calls = result.total_metric_calls or 0
    logger.info(f"GEPA optimization complete. Best score: {best_score:.3f}, Metric calls: {metric_calls}")

    return optimized_prompt, result
