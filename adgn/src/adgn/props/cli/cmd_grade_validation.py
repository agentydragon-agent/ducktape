"""Grade validation set: ensure complete critic and grader coverage across all prompts."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
from uuid import UUID

import aiodocker
from sqlalchemy import select
import typer
from typer_di import Depends

from adgn.cli_utils import async_run
from adgn.openai_utils.client_factory import build_client
from adgn.props.cli import common_options as opt
from adgn.props.cli.resources import get_database_config, get_hydrator
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticContextLengthExceeded, CriticInput, CriticMaxTurnsExceeded, CriticSuccess
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Example, GraderRun, Prompt, Snapshot
from adgn.props.db.query_builders import query_prompt_performance_stats
from adgn.props.db.snapshots import DBGraderSuccess
from adgn.props.display import short_sha, short_uuid
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


@async_run
async def cmd_grade_validation(
    grader_model: str = opt.OPT_GRADER_MODEL,
    critic_model: str = opt.OPT_CRITIC_MODEL,
    max_parallel: int = opt.OPT_MAX_PARALLEL,
    verbose: bool = opt.OPT_VERBOSE,
    hydrator: SnapshotHydrator = Depends(get_hydrator),
) -> None:
    """Grade validation set: ensure complete critic and grader coverage across all prompts.

    For each validation snapshot example:
    1. For each (example, prompt) pair:
       a. Check if critique exists (via CriticRun)
       b. If not, RUN critic to generate it
    2. For each critique:
       a. Check if grader run exists (for ANY model)
       b. If not, RUN grader with specified grader_model

    This ensures we have complete evaluation coverage for validation set terminal metrics.

    Note: Validation/test snapshots should have exactly one example each (full-specimen scope).
    """
    docker_client = aiodocker.Docker()
    db_config = get_database_config()
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
                .order_by(Example.snapshot_slug, Example.files_hash)
                .all()
            )

            if not validation_examples:
                typer.echo("No validation examples found")
                return

            typer.echo(f"Found {len(validation_examples)} validation examples")

            # Get all prompts in the same order as stats command displays them
            # (ordered by valid LCB desc, train LCB desc, created_at desc)
            prompt_perf_rows = query_prompt_performance_stats(session, limit=1000)
            ordered_prompt_sha256s = [row.prompt_sha256 for row in prompt_perf_rows]

            # Also get any prompts not yet evaluated (not in perf stats)
            all_prompts_query = session.query(Prompt).all()
            unevaluated_shas = [
                p.prompt_sha256 for p in all_prompts_query if p.prompt_sha256 not in ordered_prompt_sha256s
            ]

            # Combine: evaluated prompts first (in priority order), then unevaluated
            all_prompt_sha256s = ordered_prompt_sha256s + unevaluated_shas

            if not all_prompt_sha256s:
                typer.echo("No prompts found in database")
                return

            typer.echo(f"Found {len(all_prompt_sha256s)} prompts\n")

            # Build work items grouped by prompt
            # Each prompt gets a list of (snapshot, files_hash, critique_id_or_none)
            # critique_id_or_none is None if critic needs to run, otherwise UUID if grader needs to run
            # files_hash is None for whole-snapshot examples
            work_items_by_prompt: dict[str, list[tuple[SnapshotSlug, str | None, UUID | None]]] = defaultdict(list)

            for example in validation_examples:
                for prompt_sha256 in all_prompt_sha256s:
                    # Check if successful critic run exists for (example, prompt)
                    # Prefer most recent successful run
                    critic_run = session.execute(
                        select(CriticRun)
                        .where(
                            CriticRun.snapshot_slug == example.snapshot_slug,  # type: ignore[arg-type]
                            CriticRun.files_hash == example.files_hash,
                            CriticRun.prompt_sha256 == prompt_sha256,
                            CriticRun.critique_id.isnot(None),  # Only successful critic runs
                        )
                        .order_by(CriticRun.created_at.desc())
                        .limit(1)
                    ).scalar_one_or_none()

                    if critic_run is None:
                        # No successful critic run exists, need to run critic then grader
                        work_items_by_prompt[prompt_sha256].append((example.snapshot_slug, example.files_hash, None))
                        continue

                    # Check if successful grader run exists for this critique
                    # Accept grader runs from ANY model
                    successful_grader_exists = session.execute(
                        select(GraderRun.id)
                        .where(
                            GraderRun.critique_id == critic_run.critique_id,
                            GraderRun.output.isnot(None),  # Only count successful runs
                        )
                        .limit(1)
                    ).first()

                    if not successful_grader_exists:
                        # Critic succeeded, need to run grader
                        work_items_by_prompt[prompt_sha256].append(
                            (example.snapshot_slug, example.files_hash, critic_run.critique_id)
                        )
                    # else: both critic and grader succeeded - nothing to do

            # Count work needed (flatten to count)
            total_pairs = len(validation_examples) * len(all_prompt_sha256s)
            all_work_items = [item for items in work_items_by_prompt.values() for item in items]
            need_critic = sum(1 for _, _, cid in all_work_items if cid is None)
            need_grader_only = sum(1 for _, _, cid in all_work_items if isinstance(cid, UUID))
            completed = total_pairs - len(all_work_items)

            typer.echo("\nWork summary:")
            typer.echo(f"  {need_critic} items need critic + grader")
            typer.echo(f"  {need_grader_only} items need grader only")
            typer.echo(f"  {completed} items complete ({completed}/{total_pairs})")

            if need_critic == 0 and need_grader_only == 0:
                typer.echo("\n✓ All validation set examples have complete coverage!")
                return

        # Phase 2: Process prompts with worker pool, examples within each prompt in parallel
        typer.echo(f"\n=== Processing {need_critic + need_grader_only} items with {max_parallel} workers ===\n")

        async def process_one(
            snapshot_slug: SnapshotSlug,
            files_hash: str | None,
            prompt_sha256: str,
            critique_id_or_none: UUID | None,
            worker_id: int,
            item_index: int,
            total_items: int,
        ) -> tuple[str, bool, bool, UUID | None]:
            """Process one work item: run critic if needed, then grader.
            Returns (status, critic_success, grader_success, grader_run_id).

            files_hash can be None for whole-snapshot examples."""
            critique_id = critique_id_or_none
            critic_success = True
            grader_success = True
            grader_run_id: UUID | None = None

            # Step 1: Run critic if needed
            if critique_id is None:
                try:
                    # Get scope files from DB
                    with get_session() as session:
                        snapshot_obj = session.execute(
                            select(Snapshot).where(
                                Snapshot.slug == snapshot_slug  # type: ignore[arg-type]
                            )
                        ).scalar_one()

                        matching_example = next((e for e in snapshot_obj.examples if e.files_hash == files_hash), None)
                        if not matching_example:
                            raise RuntimeError(f"Example not found for files_hash={files_hash}")

                        scope_files = matching_example.files

                    # Run critic (compositor handles snapshot hydration internally)
                    # Use AllFilesScope for whole-snapshot examples, ExplicitFileScope for per-file
                    files_scope: CriticScopeSpec
                    if scope_files is None:
                        files_scope = AllFilesScope()
                    else:
                        files_scope = ExplicitFileScope(files=[str(f) for f in scope_files])

                    critic_input = CriticInput(
                        snapshot_slug=snapshot_slug, files=files_scope, prompt_sha256=prompt_sha256
                    )

                    (critic_output, _critic_run_id, critique_id) = await run_critic(
                        input_data=critic_input,
                        client=critic_client,
                        docker_client=docker_client,
                        hydrator=hydrator,
                        prompt_optimization_run_id=None,
                        mount_properties=True,
                        verbose=verbose,
                        max_turns=100,
                    )

                    # Check if critic succeeded - if not, skip grading
                    if not isinstance(critic_output, CriticSuccess):
                        # Critic failed (max_turns_exceeded or context_length_exceeded)
                        if isinstance(critic_output, CriticMaxTurnsExceeded):
                            status_msg = "max_turns_exceeded"
                        elif isinstance(critic_output, CriticContextLengthExceeded):
                            status_msg = "context_length_exceeded"
                        else:
                            status_msg = f"unknown_error_{critic_output.tag}"

                        if not verbose:
                            typer.echo(
                                f"[W{worker_id} {item_index}/{total_items}] ⚠ Critic {status_msg}: {snapshot_slug} x {short_sha(prompt_sha256)}"
                            )
                        return (status_msg, False, False, None)

                    assert critique_id is not None, "CriticSuccess should have critique_id"

                    if not verbose:
                        typer.echo(
                            f"[W{worker_id} {item_index}/{total_items}] ✓ Critic {snapshot_slug} x {short_sha(prompt_sha256)} → {short_uuid(critique_id)}"
                        )
                except Exception as e:
                    typer.echo(
                        f"[W{worker_id} {item_index}/{total_items}] ✗ Critic failed {snapshot_slug} x {short_sha(prompt_sha256)}: {e}",
                        err=True,
                    )
                    return ("critic_failed", False, False, None)

            # At this point, critique_id must be a UUID (str case was handled by early return)
            assert isinstance(critique_id, UUID)

            # Step 2: Run grader
            try:
                with get_session() as session:
                    grader_run_id = await grade_critique_by_id(
                        session,
                        critique_id,
                        grader_client,
                        docker_client,
                        hydrator,
                        db_config,
                        verbose=verbose,
                        max_turns=200,
                    )

                    # Fetch recall for progress message
                    grader_run = session.get(GraderRun, grader_run_id)
                    assert grader_run is not None
                    assert grader_run.output is not None

                    if isinstance(grader_run.output, DBGraderSuccess):
                        # Show absolute numbers instead of percentage
                        if grader_run.output.occurrence_results:
                            total_credit = sum(o.found_credit for o in grader_run.output.occurrence_results)
                            n_occurrences = len(grader_run.output.occurrence_results)
                            result_str = f"{total_credit:.1f} / {n_occurrences} found"
                        else:
                            result_str = "0 / 0 found"
                    else:
                        result_str = "max_turns_exceeded"

                    if not verbose:
                        typer.echo(
                            f"[W{worker_id} {item_index}/{total_items}] ✓ Graded {short_uuid(critique_id)} → {short_uuid(grader_run_id)} "
                            f"({result_str})"
                        )
            except Exception as e:
                typer.echo(
                    f"[W{worker_id} {item_index}/{total_items}] ✗ Grader failed {short_uuid(critique_id)}: {e}",
                    err=True,
                )
                return ("grader_failed", critic_success, False, None)

            return ("complete", critic_success, grader_success, grader_run_id)

        # Worker pool: process (prompt, example) pairs with queue
        all_results: list[tuple[str, bool, bool, UUID | None]] = []
        results_lock = asyncio.Lock()

        # Build queue of (prompt_sha256, snapshot_slug, files_hash, critique_id_or_none) tuples
        # Ordered by prompt priority (same order as stats table: valid LCB desc, train LCB desc, created_at desc)
        # files_hash is None for whole-snapshot examples
        work_queue: asyncio.Queue[tuple[str, SnapshotSlug, str | None, UUID | None]] = asyncio.Queue()
        total_items = 0
        for prompt_sha256 in all_prompt_sha256s:
            items = work_items_by_prompt.get(prompt_sha256, [])
            for snapshot_slug, files_hash, critique_id_or_none in items:
                await work_queue.put((prompt_sha256, snapshot_slug, files_hash, critique_id_or_none))
                total_items += 1

        items_processed = 0
        progress_lock = asyncio.Lock()

        async def worker(worker_id: int) -> None:
            """Worker that grabs (prompt, example) items from queue and processes them."""
            nonlocal items_processed

            while True:
                try:
                    prompt_sha256, snapshot_slug, files_hash, critique_id_or_none = work_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                async with progress_lock:
                    items_processed += 1
                    item_index = items_processed

                result = await process_one(
                    snapshot_slug, files_hash, prompt_sha256, critique_id_or_none, worker_id, item_index, total_items
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
        typer.echo("\nFor recall metrics, query: aggregated_recall_by_prompt or aggregated_recall_by_example views")
    finally:
        await docker_client.close()
