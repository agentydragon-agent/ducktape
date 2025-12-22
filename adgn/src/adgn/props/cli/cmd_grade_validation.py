"""Grade validation set: ensure complete critic and grader coverage across all definitions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import logging
from uuid import UUID

import aiodocker
from sqlalchemy import func, select
import typer
from typer_di import Depends

from adgn.cli_utils import async_run
from adgn.openai_utils.client_factory import build_client
from adgn.props.agent_types import AgentType
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli import common_options as opt
from adgn.props.cli.resources import get_database_config, get_hydrator
from adgn.props.critic.critic import run_critic
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import GRADER_AGENT_DEFINITION_ID
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentDefinition, AgentRun, AgentRunStatus, GradingDecision, Snapshot
from adgn.props.db.query_builders import query_definition_performance_stats
from adgn.props.display import short_uuid
from adgn.props.grader.grader import grade_critic_run_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


@dataclass
class ValidationWorkItem:
    """Work item for validation grading."""

    snapshot_slug: SnapshotSlug
    scope_hash: str
    parent_agent_run_id: UUID | None


@async_run
async def cmd_grade_validation(
    grader_model: str = opt.OPT_GRADER_MODEL,
    critic_model: str = opt.OPT_CRITIC_MODEL,
    max_parallel: int = opt.OPT_MAX_PARALLEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Grade validation set: ensure complete critic and grader coverage across all definitions.

    For each validation snapshot example:
    1. For each (example, critic_definition) pair:
       a. Check if successful critic run exists (via AgentRun)
       b. If not, RUN critic to generate it
    2. For each successful critic run:
       a. Check if grader run exists (for ANY model)
       b. If not, RUN grader with specified grader_model

    This ensures we have complete evaluation coverage for validation set terminal metrics.

    Note: Validation/test snapshots should have exactly one example each (full-specimen scope).
    """
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
    workspace_manager = WorkspaceManager.from_env()
    try:
        critic_client = build_client(critic_model)
        grader_client = build_client(grader_model)

        # Phase 1: Find all work items (snapshot, scope, prompt) combinations
        with get_session() as session:
            # Query validation examples directly (same logic as stats/datapoints)
            validation_examples = (
                session.query(Example)
                .join(Snapshot, Snapshot.slug == Example.snapshot_slug)
                .where(Snapshot.split == Split.VALID)
                .order_by(Example.snapshot_slug, Example.scope_hash)
                .all()
            )

            if not validation_examples:
                typer.echo("No validation examples found")
                return

            typer.echo(f"Found {len(validation_examples)} validation examples")

            # Get all critic definitions in the same order as stats command displays them
            # (ordered by valid LCB desc, train LCB desc, created_at desc)
            perf_rows = query_definition_performance_stats(session, limit=1000)
            ordered_definition_ids = [row.agent_definition_id for row in perf_rows]

            # Also get any critic definitions not yet evaluated (not in perf stats)
            all_critic_defs = (
                session.query(AgentDefinition).filter(AgentDefinition.agent_type == AgentType.CRITIC).all()
            )
            unevaluated_defs = [d.id for d in all_critic_defs if d.id not in ordered_definition_ids]

            # Combine: evaluated definitions first (in priority order), then unevaluated
            all_definition_ids = ordered_definition_ids + unevaluated_defs

            if not all_definition_ids:
                raise typer.BadParameter(
                    "No critic definitions found in database - run 'adgn-properties db sync' first"
                )

            typer.echo(f"Found {len(all_definition_ids)} critic definitions\n")

            # Build work items grouped by definition
            # Each definition gets a list of ValidationWorkItem
            # parent_agent_run_id is None if critic needs to run, otherwise UUID if grader needs to run
            work_items_by_definition: dict[str, list[ValidationWorkItem]] = defaultdict(list)

            for example in validation_examples:
                for definition_id in all_definition_ids:
                    # Check if successful critic run exists for (example, definition)
                    # Query AgentRun by agent_definition_id and type_config fields
                    critic_run = (
                        session.query(AgentRun)
                        .filter(
                            AgentRun.agent_definition_id == definition_id,
                            AgentRun.type_config["snapshot_slug"].astext == example.snapshot_slug,
                            AgentRun.type_config["scope_hash"].astext == example.scope_hash,
                            AgentRun.status == AgentRunStatus.COMPLETED,
                        )
                        .order_by(AgentRun.created_at.desc())
                        .first()
                    )

                    if critic_run is None:
                        # No successful critic run exists, need to run critic then grader
                        work_items_by_definition[definition_id].append(
                            ValidationWorkItem(
                                snapshot_slug=example.snapshot_slug,
                                scope_hash=example.scope_hash,
                                parent_agent_run_id=None,
                            )
                        )
                        continue

                    # Check if successful grader run exists for this critic run
                    # Accept grader runs from ANY model
                    successful_grader_exists = (
                        session.query(AgentRun)
                        .filter(
                            AgentRun.agent_definition_id == GRADER_AGENT_DEFINITION_ID,
                            AgentRun.type_config["graded_agent_run_id"].astext == str(critic_run.agent_run_id),
                            AgentRun.status == AgentRunStatus.COMPLETED,
                        )
                        .first()
                    )

                    if not successful_grader_exists:
                        # Critic succeeded, need to run grader
                        work_items_by_definition[definition_id].append(
                            ValidationWorkItem(
                                snapshot_slug=example.snapshot_slug,
                                scope_hash=example.scope_hash,
                                parent_agent_run_id=critic_run.agent_run_id,
                            )
                        )
                    # else: both critic and grader succeeded - nothing to do

            # Count work needed (flatten to count)
            total_pairs = len(validation_examples) * len(all_definition_ids)
            all_work_items = [item for items in work_items_by_definition.values() for item in items]
            need_critic = sum(1 for item in all_work_items if item.parent_agent_run_id is None)
            need_grader_only = sum(1 for item in all_work_items if isinstance(item.parent_agent_run_id, UUID))
            completed = total_pairs - len(all_work_items)

            typer.echo("\nWork summary:")
            typer.echo(f"  {need_critic} items need critic + grader")
            typer.echo(f"  {need_grader_only} items need grader only")
            typer.echo(f"  {completed} items complete ({completed}/{total_pairs})")

            if need_critic == 0 and need_grader_only == 0:
                typer.echo("\n✓ All validation set examples have complete coverage!")
                return

        # Phase 2: Process definitions with worker pool, examples within each definition in parallel
        typer.echo(f"\n=== Processing {need_critic + need_grader_only} items with {max_parallel} workers ===\n")

        async def process_one(
            snapshot_slug: SnapshotSlug,
            scope_hash: str,
            definition_id: str,
            critic_run_id_or_none: UUID | None,
            worker_id: int,
            item_index: int,
            total_items: int,
        ) -> tuple[str, bool, bool, UUID | None]:
            """Process one work item: run critic if needed, then grader.
            Returns (status, critic_success, grader_success, grader_run_id)."""
            critic_run_id = critic_run_id_or_none
            critic_success = True
            grader_success = True
            grader_run_id: UUID | None = None

            # Step 1: Run critic if needed
            if critic_run_id is None:
                try:
                    # Get scope from DB
                    with get_session() as session:
                        snapshot_obj = session.execute(
                            select(Snapshot).where(
                                Snapshot.slug == snapshot_slug  # type: ignore[arg-type]
                            )
                        ).scalar_one()

                        matching_example = next((e for e in snapshot_obj.examples if e.scope_hash == scope_hash), None)
                        if not matching_example:
                            raise RuntimeError(f"Example not found for scope_hash={scope_hash}")

                        example_scope = matching_example.scope

                    # Run critic using definition-based run_critic()
                    (critic_run_id, status) = await run_critic(
                        definition_id=definition_id,
                        snapshot_slug=snapshot_slug,
                        scope=example_scope,
                        client=critic_client,
                        docker_client=docker_client,
                        hydrator=hydrator,
                        db_config=db_config,
                        workspace_manager=workspace_manager,
                        parent_agent_run_id=None,
                        mount_properties=True,
                        verbose=verbose,
                        max_turns=100,
                    )

                    # Check if critic succeeded - if not, skip grading
                    if status != AgentRunStatus.COMPLETED:
                        # Critic failed (max_turns_exceeded or context_length_exceeded)
                        if not verbose:
                            typer.echo(
                                f"[W{worker_id} {item_index}/{total_items}] ⚠ Critic {status}: {snapshot_slug} x {definition_id}"
                            )
                        return (status, False, False, None)

                    if not verbose:
                        typer.echo(
                            f"[W{worker_id} {item_index}/{total_items}] ✓ Critic {snapshot_slug} x {definition_id} → {short_uuid(critic_run_id)}"
                        )
                except Exception as e:
                    typer.echo(
                        f"[W{worker_id} {item_index}/{total_items}] ✗ Critic failed {snapshot_slug} x {definition_id}: {e}",
                        err=True,
                    )
                    return ("critic_failed", False, False, None)

            # Step 2: Run grader
            try:
                with get_session() as session:
                    grader_run_id = await grade_critic_run_by_id(
                        session,
                        critic_run_id,
                        grader_client,
                        docker_client,
                        hydrator,
                        db_config,
                        workspace_manager,
                        verbose=verbose,
                        max_turns=200,
                    )

                    # Fetch recall for progress message (direct query to grading_decisions)
                    grader_run = session.get(AgentRun, grader_run_id)
                    assert grader_run is not None

                    if grader_run.status == AgentRunStatus.COMPLETED:
                        # Show absolute numbers instead of percentage (query grading_decisions)
                        total_credit = (
                            session.query(func.sum(GradingDecision.credit))
                            .filter_by(agent_run_id=grader_run_id)
                            .filter(GradingDecision.target_tp_id.isnot(None))  # Only TP matches
                            .scalar()
                            or 0.0
                        )
                        n_occurrences = (
                            session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
                            .filter_by(agent_run_id=grader_run_id)
                            .filter(GradingDecision.target_tp_id.isnot(None))
                            .distinct()
                            .count()
                        )
                        result_str = f"{total_credit:.1f} / {n_occurrences} found"
                    else:
                        result_str = f"status={grader_run.status.value}"

                    if not verbose:
                        typer.echo(
                            f"[W{worker_id} {item_index}/{total_items}] ✓ Graded {short_uuid(critic_run_id)} → {short_uuid(grader_run_id)} "
                            f"({result_str})"
                        )
            except Exception as e:
                typer.echo(
                    f"[W{worker_id} {item_index}/{total_items}] ✗ Grader failed {short_uuid(critic_run_id)}: {e}",
                    err=True,
                )
                return ("grader_failed", critic_success, False, None)

            return ("complete", critic_success, grader_success, grader_run_id)

        # Worker pool: process (definition, example) pairs with queue
        all_results: list[tuple[str, bool, bool, UUID | None]] = []
        results_lock = asyncio.Lock()

        # Build queue of (definition_id, ValidationWorkItem) tuples
        # Ordered by definition priority (same order as stats table: valid LCB desc, train LCB desc, created_at desc)
        work_queue: asyncio.Queue[tuple[str, ValidationWorkItem]] = asyncio.Queue()
        total_items = 0
        for definition_id in all_definition_ids:
            items = work_items_by_definition.get(definition_id, [])
            for item in items:
                await work_queue.put((definition_id, item))
                total_items += 1

        items_processed = 0
        progress_lock = asyncio.Lock()

        async def worker(worker_id: int) -> None:
            """Worker that grabs (definition, work_item) items from queue and processes them."""
            nonlocal items_processed

            while True:
                try:
                    definition_id, work_item = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                async with progress_lock:
                    items_processed += 1
                    item_index = items_processed

                result = await process_one(
                    work_item.snapshot_slug,
                    work_item.scope_hash,
                    definition_id,
                    work_item.parent_agent_run_id,
                    worker_id,
                    item_index,
                    total_items,
                )

                async with results_lock:
                    all_results.append(result)

                work_queue.task_done()

        # Run workers
        await asyncio.gather(*[worker(i) for i in range(1, max_parallel + 1)])

        results = all_results

        # Summary
        complete = sum(1 for status, _, _, _ in results if status == "complete")
        critic_failures = sum(1 for status, _, _, _ in results if status == "critic_failed")
        grader_failures = sum(1 for status, _, _, _ in results if status == "grader_failed")

        typer.echo("\n=== Final Summary ===")
        typer.echo(f"Complete: {complete}")
        typer.echo(f"Critic failures: {critic_failures}")
        typer.echo(f"Grader failures: {grader_failures}")
        typer.echo("\nFor recall metrics, query: aggregated_recall_by_definition or aggregated_recall_by_example views")
    finally:
        await docker_client.close()
