"""Grade validation set: ensure complete critic and grader coverage across all prompts."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import aiodocker
from sqlalchemy import select
import typer
from typer_di import Depends

from adgn.cli_utils import async_run
from adgn.openai_utils.client_factory import build_client
from adgn.props.cli import common_options as opt
from adgn.props.cli.resources import get_hydrator
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Example, GraderRun, Prompt, Snapshot
from adgn.props.display import short_sha, short_uuid
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ExplicitFileScope
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

            # Get all prompts
            all_prompts = session.query(Prompt).all()

            if not all_prompts:
                typer.echo("No prompts found in database")
                return

            typer.echo(f"Found {len(all_prompts)} prompts\n")

            # Build list of all work items: (snapshot, files_hash, prompt, critique_id_or_none)
            # critique_id_or_none is None if critic needs to run, otherwise UUID if grader needs to run
            work_items: list[tuple[SnapshotSlug, str, str, UUID | None]] = []

            for example in validation_examples:
                for prompt in all_prompts:
                    # Check if successful critic run exists for (example, prompt)
                    # Prefer most recent successful run
                    critic_run = session.execute(
                        select(CriticRun)
                        .where(
                            CriticRun.snapshot_slug == example.snapshot_slug,  # type: ignore[arg-type]
                            CriticRun.files_hash == example.files_hash,
                            CriticRun.prompt_sha256 == prompt.prompt_sha256,
                            CriticRun.critique_id.isnot(None),  # Only successful critic runs
                        )
                        .order_by(CriticRun.created_at.desc())
                        .limit(1)
                    ).scalar_one_or_none()

                    if critic_run is None:
                        # No successful critic run exists, need to run critic then grader
                        work_items.append((example.snapshot_slug, example.files_hash, prompt.prompt_sha256, None))
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
                        work_items.append(
                            (example.snapshot_slug, example.files_hash, prompt.prompt_sha256, critic_run.critique_id)
                        )
                    # else: both critic and grader succeeded - nothing to do

            # Count work needed
            total_pairs = len(validation_examples) * len(all_prompts)
            need_critic = sum(1 for _, _, _, cid in work_items if cid is None)
            need_grader_only = sum(1 for _, _, _, cid in work_items if isinstance(cid, UUID))
            completed = total_pairs - len(work_items)

            typer.echo("\nWork summary:")
            typer.echo(f"  {need_critic} items need critic + grader")
            typer.echo(f"  {need_grader_only} items need grader only")
            typer.echo(f"  {completed} items complete ({completed}/{total_pairs})")

            if need_critic == 0 and need_grader_only == 0:
                typer.echo("\n✓ All validation set examples have complete coverage!")
                return

        # Phase 2: Process all work items in parallel (each item processes serially: critic→grader)
        typer.echo(f"\n=== Processing {need_critic + need_grader_only} items with max_parallel={max_parallel} ===\n")
        semaphore = asyncio.Semaphore(max_parallel)

        async def process_one(
            snapshot_slug: SnapshotSlug,
            files_hash: str,
            prompt_sha256: str,
            critique_id_or_none: UUID | None,
            index: int,
            total: int,
        ) -> tuple[str, bool, bool, UUID | None]:
            """Process one work item: run critic if needed, then grader.
            Returns (status, critic_success, grader_success, grader_run_id)"""
            async with semaphore:
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
                                select(Snapshot)
                                .join(Snapshot.examples)
                                .where(
                                    Snapshot.slug == snapshot_slug  # type: ignore[arg-type]
                                )
                            ).scalar_one()

                            matching_example = next(
                                (e for e in snapshot_obj.examples if e.files_hash == files_hash), None
                            )
                            if not matching_example:
                                raise RuntimeError(f"Example not found for files_hash={files_hash}")

                            scope_files = matching_example.files

                        # Hydrate snapshot and run critic
                        async with hydrator.hydrate(snapshot_slug) as hydrated:
                            critic_input = CriticInput(
                                snapshot_slug=snapshot_slug,
                                files=ExplicitFileScope(files=[str(f) for f in scope_files]),
                                prompt_sha256=prompt_sha256,
                            )

                            (_critic_output, _critic_run_id, critique_id) = await run_critic(
                                input_data=critic_input,
                                client=critic_client,
                                docker_client=docker_client,
                                content_root=hydrated.content_root,
                                prompt_optimization_run_id=None,
                                mount_properties=True,
                                verbose=verbose,
                            )

                            if not verbose:
                                typer.echo(
                                    f"[{index}/{total}] ✓ Critic {snapshot_slug} x {short_sha(prompt_sha256)} → {short_uuid(critique_id)}"
                                )
                    except Exception as e:
                        typer.echo(
                            f"[{index}/{total}] ✗ Critic failed {snapshot_slug} x {short_sha(prompt_sha256)}: {e}",
                            err=True,
                        )
                        return ("critic_failed", False, False, None)

                # At this point, critique_id must be a UUID (str case was handled by early return)
                assert isinstance(critique_id, UUID)

                # Step 2: Run grader
                try:
                    with get_session() as session:
                        grader_run_id = await grade_critique_by_id(
                            session, critique_id, grader_client, docker_client, verbose=verbose
                        )

                        # Fetch recall for progress message
                        grader_run = session.get(GraderRun, grader_run_id)
                        recall_pct = grader_run.output.recall * 100.0 if grader_run and grader_run.output else 0.0

                        if not verbose:
                            typer.echo(
                                f"[{index}/{total}] ✓ Graded {short_uuid(critique_id)} → {short_uuid(grader_run_id)} "
                                f"(recall: {recall_pct:.1f}%)"
                            )
                except Exception as e:
                    typer.echo(f"[{index}/{total}] ✗ Grader failed {short_uuid(critique_id)}: {e}", err=True)
                    return ("grader_failed", critic_success, False, None)

                return ("complete", critic_success, grader_success, grader_run_id)

        # Process all work items
        results = await asyncio.gather(
            *[
                process_one(snapshot, files_hash, prompt_sha256, critique_id, i, len(work_items))
                for i, (snapshot, files_hash, prompt_sha256, critique_id) in enumerate(work_items, 1)
            ]
        )

        # Summary
        complete = sum(1 for status, _, _, _ in results if status == "complete")
        critic_failures = sum(1 for status, _, _, _ in results if status == "critic_failed")
        grader_failures = sum(1 for status, _, _, _ in results if status == "grader_failed")

        # Collect grader run IDs for recall calculation
        grader_run_ids = [gid for _, _, _, gid in results if gid is not None]

        typer.echo("\n=== Final Summary ===")
        typer.echo(f"Complete: {complete}")
        typer.echo(f"Critic failures: {critic_failures}")
        typer.echo(f"Grader failures: {grader_failures}")

        # Calculate and print recall statistics
        if grader_run_ids:
            with get_session() as session:
                grader_runs = session.query(GraderRun).filter(GraderRun.id.in_(grader_run_ids)).all()

                if grader_runs:
                    recalls = []

                    for run in grader_runs:
                        recall = run.output.recall
                        recalls.append(recall)

                    typer.echo("\n=== Metrics ===")
                    typer.echo(f"Mean recall:    {sum(recalls) / len(recalls):.3f}")
                    typer.echo(f"Min recall:     {min(recalls):.3f}")
                    typer.echo(f"Max recall:     {max(recalls):.3f}")
                    typer.echo(f"Samples:        {len(grader_runs)}")
    finally:
        await docker_client.close()
