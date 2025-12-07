"""GEPA adapter for props critic optimization.

Integrates with gepa-ai/gepa to optimize the critic system prompt using
evolutionary search with rich feedback from execution traces and grader output.

Usage:
    from pathlib import Path
    from gepa import optimize
    from adgn.props.gepa.gepa_adapter import CriticAdapter, load_datasets

    adapter = CriticAdapter(hydrator, critic_client, grader_client, run_dir=Path("/tmp/gepa_run"))
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
from datetime import datetime
from itertools import chain
import json
import logging
from pathlib import Path
import pickle
import tempfile
from typing import Any, cast as type_cast
from uuid import UUID

import gepa
from gepa.core.result import GEPAResult
from gepa.strategies.instruction_proposal import InstructionProposalSignature
import litellm
from pydantic import BaseModel
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB

from adgn.agent.events import REFLECTION_EVENT_TYPES, EventType
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput, CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, Critique, Event, GraderRun as DBGraderRun, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.files_hash import hash_critic_scope_files
from adgn.props.gepa.models import SnapshotInput
from adgn.props.gepa.warm_start import build_historical_gepa_state
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.grader.models import GraderOutput, GradeSubmitInput
from adgn.props.snapshot_hydrator import SnapshotHydrator
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


# =============================================================================
# Event Filtering
# =============================================================================


def _filter_reflection_events(transcript_id: UUID) -> list[EventType]:
    """Load and filter events for GEPA reflection dataset.

    Fetches events for a transcript and filters to reflection-relevant types
    (excludes ApiRequest/Response to prevent O(n²) context blowup in reflection LM).

    Args:
        transcript_id: Transcript UUID to fetch events for

    Returns:
        List of filtered events (ToolCall, ToolCallOutput, AssistantText, ReasoningItem)
    """
    with get_session() as session:
        event_rows = (
            session.query(Event).filter(Event.transcript_id == transcript_id).order_by(Event.sequence_num).all()
        )
        # Filter using isinstance against REFLECTION_EVENT_TYPES tuple
        return type_cast(
            list[EventType], [e.payload for e in event_rows if isinstance(e.payload, REFLECTION_EVENT_TYPES)]
        )


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class CriticTrajectory:
    """Execution trajectory for a critic run."""

    transcript_id: UUID
    events: list[EventType]
    critique_payload: CriticSubmitPayload


@dataclass
class CriticOutput:
    """Output from a critic evaluation."""

    grader_output: GradeSubmitInput | None
    critique_id: UUID


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
    trajectory: CriticTrajectory
    grader_output: GradeSubmitInput


# =============================================================================
# GEPA Adapter
# =============================================================================


class CriticAdapter(gepa.GEPAAdapter[SnapshotInput, CriticTrajectory, CriticOutput]):
    """GEPA adapter for the props critic.

    Implements the GEPAAdapter protocol to allow GEPA to optimize
    the critic system prompt using your existing infrastructure.

    DataInst Type and Checkpointing:
    --------------------------------
    DataInst = SnapshotInput (snapshot_slug + target_files)

    GEPA's ListDataLoader maps SnapshotInput → integer DataId via list position.
    Checkpoints store scores keyed by these integers: {0: 0.85, 2: 0.90, ...}

    For warm-start to work, load_datasets() MUST return datasets in deterministic
    order across all runs. This is enforced via:
    - Snapshot queries: order_by(Snapshot.slug)
    - CriticScope relationship: order_by="CriticScopeDB.id"

    See warm_start.py for checkpoint reconstruction from historical database runs.
    """

    def __init__(
        self,
        hydrator: SnapshotHydrator,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        run_dir: Path,
        reflection_model: str | None = None,
        verbose: bool = False,
        max_parallelism: int = 20,
    ):
        self.hydrator = hydrator
        self.critic_client = critic_client
        self.grader_client = grader_client
        self.reflection_model = reflection_model
        self.verbose = verbose
        self.max_parallelism = max_parallelism

        # Always set up proposal logging if reflection_model provided
        if reflection_model:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = run_dir / f"gepa_proposals_{timestamp}.jsonl"
            self._setup_proposal_logging(log_file)
            logger.info(f"GEPA proposal logging enabled: {log_file.absolute()}")
        else:
            # Use GEPA's default proposal implementation
            self.propose_new_texts = None

    def _setup_proposal_logging(self, log_file: Path) -> None:
        """Set up logging of GEPA's proposal step (reflection LM calls).

        Replaces GEPA's default propose_new_texts implementation with a logging wrapper
        that replicates the exact same behavior but logs all LLM calls to a JSONL file.

        This method sets self.propose_new_texts to a custom function that:
        - Uses InstructionProposalSignature (same as GEPA's default)
        - Calls litellm.completion with self.reflection_model (same as GEPA does)
        - Logs input (prompt, current instruction, feedback) and output (new instruction)

        Args:
            log_file: Path to JSONL file where proposal calls will be logged

        Example log entry format:
            {"timestamp": "2025-01-15T10:30:00", "call_id": 1, "component": "system_prompt",
             "type": "input", "current_instruction": "...", "feedback_count": 3, "prompt": "..."}
            {"timestamp": "2025-01-15T10:30:05", "call_id": 1, "component": "system_prompt",
             "type": "output", "raw_response": "...", "new_instruction": "..."}
        """
        call_count = 0

        def propose_new_texts(
            candidate: dict[str, str],
            reflective_dataset: Mapping[str, Sequence[Mapping[str, Any]]],
            components_to_update: list[str],
        ) -> dict[str, str]:
            """Custom propose_new_texts that replicates GEPA's default with logging.

            Mirrors the implementation in gepa.proposer.reflective_mutation.reflective_mutation
            but adds structured logging before/after each LLM call.
            """
            nonlocal call_count
            new_texts: dict[str, str] = {}

            for name in components_to_update:
                # Skip if no data (same as GEPA does)
                if name not in reflective_dataset or not reflective_dataset.get(name):
                    continue

                call_count += 1
                base_instruction = candidate[name]
                dataset_with_feedback = reflective_dataset[name]

                # Build the prompt (same as InstructionProposalSignature.run does)
                input_dict = {
                    "current_instruction_doc": base_instruction,
                    "dataset_with_feedback": dataset_with_feedback,
                    "prompt_template": None,  # Uses default template
                }
                full_prompt = InstructionProposalSignature.prompt_renderer(input_dict)

                # Log input
                with log_file.open("a") as f:
                    f.write(
                        json.dumps(
                            {
                                "timestamp": datetime.now().isoformat(),
                                "call_id": call_count,
                                "component": name,
                                "type": "input",
                                "current_instruction": base_instruction,
                                "feedback_count": len(dataset_with_feedback),
                                "prompt": full_prompt,
                            }
                        )
                        + "\n"
                    )

                # Call LLM (same as GEPA does when reflection_lm is a string)
                completion = litellm.completion(
                    model=self.reflection_model, messages=[{"role": "user", "content": full_prompt}]
                )
                lm_out = (completion.choices[0].message.content or "").strip()

                # Extract the new instruction (same as InstructionProposalSignature does)
                result = InstructionProposalSignature.output_extractor(lm_out)
                new_instruction = result["new_instruction"]

                # Log output
                with log_file.open("a") as f:
                    f.write(
                        json.dumps(
                            {
                                "timestamp": datetime.now().isoformat(),
                                "call_id": call_count,
                                "component": name,
                                "type": "output",
                                "raw_response": lm_out,
                                "new_instruction": new_instruction,
                            }
                        )
                        + "\n"
                    )

                new_texts[name] = new_instruction

            return new_texts

        self.propose_new_texts = propose_new_texts

    @staticmethod
    def _build_critic_output(grader_output: GraderOutput, critique_id: UUID) -> CriticOutput:
        """Build CriticOutput from grader output and critique ID.

        Args:
            grader_output: GraderOutput Pydantic model (extracted inside session)
            critique_id: Critique UUID

        Returns:
            CriticOutput with grader data
        """
        return CriticOutput(grader_output=grader_output.grade, critique_id=critique_id)

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
        self, specimen_input: SnapshotInput, prompt_sha256: str, capture_traces: bool, semaphore: asyncio.Semaphore
    ) -> EvaluationResult:
        """Evaluate a single specimen (for parallel execution).

        Uses semaphore to limit concurrent critic/grader runs.
        """
        async with semaphore:
            return await self._evaluate_one_specimen_impl(specimen_input, prompt_sha256, capture_traces)

    async def _evaluate_one_specimen_impl(
        self, specimen_input: SnapshotInput, prompt_sha256: str, capture_traces: bool
    ) -> EvaluationResult:
        """Implementation of single specimen evaluation (called under semaphore)."""
        slug = specimen_input.slug

        # Run critic - use specimen's target_files for consistent cache keys
        async with self.hydrator.hydrate(slug) as hydrated:
            critic_input = CriticInput(
                snapshot_slug=slug,
                files=specimen_input.target_files,  # Use target_files for cache consistency
                prompt_sha256=prompt_sha256,
            )

            critic_output, critic_run_id, critique_id = await run_critic(
                input_data=critic_input,
                client=self.critic_client,
                content_root=hydrated.content_root,
                mount_properties=True,
                verbose=self.verbose,
            )

        # Get transcript_id
        with get_session() as session:
            critic_run = session.get(DBCriticRun, critic_run_id)
            assert critic_run is not None, f"CriticRun {critic_run_id} not found"
            transcript_id = critic_run.transcript_id

        # Load and filter events for reflection (separate session)
        events: list[EventType] = []
        if capture_traces:
            events = _filter_reflection_events(transcript_id)

        # Grade and fetch output in single session
        # CRITICAL: Extract grader_output inside session before object becomes detached
        with get_session() as session:
            grader_run_id = await grade_critique_by_id(session, critique_id, self.grader_client, verbose=self.verbose)
            grader_run = session.get(DBGraderRun, grader_run_id)
            assert grader_run is not None, f"GraderRun {grader_run_id} not found"
            # Access output while still in session - grader_run.output is GraderOutput (PydanticColumn)
            grader_output = grader_run.output
            score = grader_output.recall

        trajectory = (
            CriticTrajectory(transcript_id=transcript_id, events=events, critique_payload=critic_output.result)
            if capture_traces
            else None
        )

        return EvaluationResult(
            output=self._build_critic_output(grader_output, critique_id), score=score, trajectory=trajectory
        )

    def _reconstruct_from_cache(
        self, transcript_id: UUID, critique_id: UUID, grader_output: GraderOutput, capture_traces: bool
    ) -> EvaluationResult:
        """Reconstruct an EvaluationResult from cached database runs.

        Args:
            transcript_id: Transcript UUID from critic run
            critique_id: Critique UUID from critic run
            grader_output: GraderOutput Pydantic model (extracted inside session at call site)
            capture_traces: Whether to fetch events for trajectory

        Returns:
            EvaluationResult with output, score, and optional trajectory

        Note:
            All data must be extracted inside the calling session to avoid
            DetachedInstanceError. See call site in _evaluate_async().
        """
        # Fetch critique for issues
        with get_session() as session:
            critique = session.get(Critique, critique_id)
            assert critique is not None, f"Critique {critique_id} not found"
            critique_payload = CriticSubmitPayload.model_validate(critique.payload)

        # Fetch trajectory if requested
        trajectory: CriticTrajectory | None = None
        if capture_traces:
            filtered_events = _filter_reflection_events(transcript_id)
            trajectory = CriticTrajectory(
                transcript_id=transcript_id, events=filtered_events, critique_payload=critique_payload
            )

        return EvaluationResult(
            output=self._build_critic_output(grader_output, critique_id),
            score=grader_output.recall,
            trajectory=trajectory,
        )

    async def _evaluate_async(
        self, batch: list[SnapshotInput], candidate: dict[str, str], capture_traces: bool
    ) -> list[EvaluationResult]:
        """Async implementation with database-backed caching.

        Three phases:
        1. Check cache: Query for existing (prompt_sha256, snapshot_slug, files_hash)
        2. Evaluate uncached: Run critic+grader only for cache misses
        3. Reorder results: Return in original batch order

        Semaphore ensures max_parallelism concurrent critic/grader runs.
        """
        # Create semaphore for this evaluation batch (scoped to this event loop)
        semaphore = asyncio.Semaphore(self.max_parallelism)

        system_prompt = candidate["system_prompt"]
        prompt_sha256 = hash_and_upsert_prompt(system_prompt)

        # Phase 1: Check DB for each input
        cached_results: dict[int, EvaluationResult] = {}  # batch_idx -> result found in DB
        uncached_inputs: list[tuple[int, SnapshotInput]] = []  # (batch_idx, input)

        with get_session() as session:
            for idx, specimen_input in enumerate(batch):
                files_hash = hash_critic_scope_files(specimen_input.target_files)

                # Query for cached run - joint query to find completed critic+grader pair
                db_row = (
                    session.query(DBCriticRun, DBGraderRun)
                    .join(DBGraderRun, DBCriticRun.critique_id == DBGraderRun.critique_id)
                    .filter(
                        DBCriticRun.prompt_sha256 == prompt_sha256,
                        DBCriticRun.snapshot_slug == specimen_input.slug,  # type: ignore[arg-type]
                        DBCriticRun.files_hash == files_hash,
                        DBCriticRun.model == self.critic_client.model,
                        DBGraderRun.model == self.grader_client.model,
                        # Ensure both runs completed successfully
                        DBCriticRun.critique_id.isnot(None),
                        DBCriticRun.output.isnot(None),
                        DBGraderRun.output.isnot(None),  # Excludes SQL NULL
                        DBGraderRun.output != cast(None, JSONB),  # Excludes JSON null
                    )
                    .first()
                )

                if db_row:
                    critic_run, grader_run = db_row
                    # CRITICAL: Extract all needed data inside session before objects become detached
                    transcript_id = critic_run.transcript_id
                    critique_id = critic_run.critique_id
                    assert critique_id is not None, "critique_id must be non-null (query ensures this)"
                    grader_output = grader_run.output
                    # Cache hit - reconstruct result
                    logger.info(
                        f"Cache HIT: {specimen_input.slug} (prompt={prompt_sha256[:8]}..., "
                        f"files_hash={files_hash[:8]}...)"
                    )
                    cached_results[idx] = self._reconstruct_from_cache(
                        transcript_id, critique_id, grader_output, capture_traces
                    )
                    continue

                # Cache miss - add to evaluation queue
                logger.info(
                    f"Cache MISS: {specimen_input.slug} (prompt={prompt_sha256[:8]}..., files_hash={files_hash[:8]}...)"
                )
                uncached_inputs.append((idx, specimen_input))

        # Phase 2: Evaluate uncached inputs in parallel
        fresh_results: dict[int, EvaluationResult] = {}
        if uncached_inputs:
            tasks = [
                asyncio.create_task(
                    self._evaluate_one_specimen(specimen_input, prompt_sha256, capture_traces, semaphore)
                )
                for _, specimen_input in uncached_inputs
            ]
            try:
                evaluated = await asyncio.gather(*tasks)
            except (KeyboardInterrupt, asyncio.CancelledError):
                # Cancel all tasks on interrupt to ensure clean shutdown
                for task in tasks:
                    if not task.done():
                        task.cancel()
                # Wait for all tasks to actually cancel
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            for (batch_idx, _), result in zip(uncached_inputs, evaluated, strict=False):
                fresh_results[batch_idx] = result

        # Phase 3: Reorder results to match original batch
        results: list[EvaluationResult] = []
        for idx in range(len(batch)):
            if idx in cached_results:
                results.append(cached_results[idx])
            elif idx in fresh_results:
                results.append(fresh_results[idx])
            else:
                raise RuntimeError(f"Missing result for batch index {idx}")

        logger.info(
            f"Evaluation complete: {len(cached_results)} cached, {len(fresh_results)} fresh, {len(results)} total"
        )

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
            # In GEPA context, grader always runs after critic
            assert output.grader_output is not None, "grader_output must be present in reflection dataset"

            example = ReflectionExample(
                component_name="system_prompt",
                current_text=candidate["system_prompt"],
                score=score,
                trajectory=trajectory,
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

    inputs: list[SnapshotInput] = []

    # Generate one SnapshotInput per critic scope
    for scope_db in snapshot.critic_scopes:
        # Pass scope spec directly - critic layer will resolve "all" sentinel
        inputs.append(SnapshotInput(slug=snapshot.slug, target_files=scope_db.files))

    return inputs


async def load_datasets() -> tuple[list[SnapshotInput], list[SnapshotInput]]:
    """Load train and validation datasets for GEPA from database.

    Builds SnapshotInputs directly from Snapshot ORM objects using critic scopes.
    Each critic scope becomes one training example. All data comes from database.

    CRITICAL: Dataset Order Determinism
    ------------------------------------
    GEPA's ListDataLoader uses list indices as DataIds (0, 1, 2, ...). When saving
    checkpoints, validation scores are keyed by these integers:
        prog_candidate_val_subscores[prog_idx] = {0: 0.85, 2: 0.90, ...}

    The mapping SnapshotInput → int is implicit via list position. For warm-start
    to work correctly, we MUST return datasets in identical order across all runs.

    Ordering strategy:
    1. Snapshots ordered by slug (deterministic string sort)
    2. Critic scopes within each snapshot ordered by id (auto-increment)

    See warm_start.py:build_historical_gepa_state() which builds the index
    mapping (snapshot_slug, files_hash) → valset_idx to match historical runs.

    Returns:
        (trainset, valset) tuple of SnapshotInput lists

    Raises:
        ValueError: If any snapshot has no critic scopes (should be caught during sync)
    """
    logger.info("Loading training examples from critic_scopes database")

    with get_session() as session:
        # CRITICAL: order_by ensures deterministic dataset order for checkpoint compatibility
        train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN).order_by(Snapshot.slug).all()
        valid_snapshots = session.query(Snapshot).filter_by(split=Split.VALID).order_by(Snapshot.slug).all()

        # Build SnapshotInputs directly from ORM (one per critic scope)
        # Must do this inside session context to access lazy-loaded relationships
        # Critic scopes are ordered by id within each snapshot (see Snapshot.critic_scopes relationship)
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
    critic_client: OpenAIModelProto,
    grader_client: OpenAIModelProto,
    *,
    reflection_model: str,
    max_metric_calls: int = 100,
    verbose: bool = False,
    warm_start: bool = True,
    max_parallelism: int = 20,
    minibatch_size: int = 3,
    use_merge: bool = True,
    max_merge_invocations: int = 5,
    merge_val_overlap_floor: int = 5,
    seed: int | None = None,
) -> tuple[str, GEPAResult[CriticOutput, Any]]:
    """Optimize critic prompt using GEPA.

    Uses critic scopes from database to generate training examples (one per scope).
    Requires all snapshots to have critic scopes defined (enforced by sync validation).

    GEPA supports two complementary strategies that work together:
    1. Reflective mutation (always enabled): LLM analyzes failures and proposes improvements
    2. Merge (optional): Genetic crossover of successful prompt variants

    Args:
        initial_prompt: Starting system prompt (ignored if warm_start=True and historical data exists)
        hydrator: SnapshotHydrator instance for source code hydration
        critic_client: LLM client for critic execution
        grader_client: LLM client for grader execution
        reflection_model: Model for GEPA's reflection
        max_metric_calls: Budget for evaluations in this run (not counting historical)
        verbose: Enable verbose logging
        warm_start: Load historical Pareto frontier from database (default: True)
        max_parallelism: Maximum concurrent critic/grader runs (default: 20)
        minibatch_size: Number of training examples per reflection iteration (default: 3)
        use_merge: Enable genetic merging of successful variants (default: True)
        max_merge_invocations: Maximum number of merge attempts (default: 5)
        merge_val_overlap_floor: Minimum validation overlap for merge candidates (default: 5)
        seed: Random seed for reproducibility (default: None, uses GEPA default of 0)

    Returns:
        (optimized_prompt, gepa_results) tuple

    Raises:
        ValueError: If any snapshot has no critic scopes
    """
    logger.info("Starting GEPA optimization")
    logger.info(f"Reflection model: {reflection_model}")
    logger.info(f"Max metric calls: {max_metric_calls}")
    logger.info(f"Minibatch size: {minibatch_size}")
    logger.info(f"Initial prompt length: {len(initial_prompt)} chars")
    logger.info(f"Warm start: {warm_start}")
    if seed is not None:
        logger.info(f"Random seed: {seed}")

    # Load datasets (always uses critic scopes from database)
    logger.info("Loading datasets...")
    trainset, valset = await load_datasets()
    logger.info(f"Loaded {len(trainset)} training examples, {len(valset)} validation examples")

    # Prepare run directory with optional warm-start checkpoint
    run_dir = None
    if warm_start:
        logger.info("Building historical GEPA state from database...")
        historical_state = build_historical_gepa_state(
            valset=valset, critic_model=critic_client.model, grader_model=grader_client.model
        )

        if historical_state:
            # Create temp directory and save checkpoint
            temp_dir = tempfile.mkdtemp(prefix="gepa_warm_start_")
            checkpoint_path = Path(temp_dir) / "gepa_state.bin"
            with checkpoint_path.open("wb") as f:
                pickle.dump(historical_state, f)
            logger.info(
                f"Saved historical state with {len(historical_state['program_candidates'])} prompts to {checkpoint_path}"
            )
            run_dir = temp_dir
        else:
            logger.warning("No historical data found - starting from seed candidate")

    # If no run_dir yet (no warm start or no historical data), create one
    if run_dir is None:
        run_dir = tempfile.mkdtemp(prefix="gepa_run_")
        logger.info(f"Created run directory: {run_dir}")

    # Create adapter
    logger.info(f"Creating CriticAdapter with max_parallelism={max_parallelism}")
    adapter = CriticAdapter(
        hydrator,
        critic_client,
        grader_client,
        Path(run_dir),
        reflection_model=reflection_model,
        verbose=verbose,
        max_parallelism=max_parallelism,
    )

    # Run optimization (reflection_lm accepts model string directly)
    logger.info(f"Starting GEPA evolutionary search (merge={'enabled' if use_merge else 'disabled'})...")
    result: GEPAResult[CriticOutput, Any] = gepa.optimize(
        seed_candidate={"system_prompt": initial_prompt},
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_model,
        max_metric_calls=max_metric_calls,
        perfect_score=1.0,  # Perfect recall
        run_dir=run_dir,  # Load checkpoint if provided
        reflection_minibatch_size=minibatch_size,
        use_merge=use_merge,
        max_merge_invocations=max_merge_invocations,
        merge_val_overlap_floor=merge_val_overlap_floor,
        seed=seed if seed is not None else 0,
    )

    optimized_prompt = result.best_candidate["system_prompt"]
    best_score = result.val_aggregate_scores[result.best_idx]
    logger.info(f"GEPA optimization complete. Best score: {best_score:.3f}, Metric calls: {result.total_metric_calls}")

    return optimized_prompt, result
