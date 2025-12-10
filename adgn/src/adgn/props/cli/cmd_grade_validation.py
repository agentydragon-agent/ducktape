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
from adgn.props.cli.resources import get_async_docker_client, get_hydrator
from adgn.props.critic.critic import run_critic
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session, init_db
from adgn.props.db.models import CriticRun, GraderRun, Prompt, Snapshot
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
    docker_client: aiodocker.Docker = Depends(get_async_docker_client),
) -> None:
    """Grade validation set: ensure complete critic and grader coverage across all prompts.

    For each validation snapshot with full-specimen critic scopes:
    1. For each (scope, prompt) pair:
       a. Check if critique exists (via CriticRun)
       b. If not, RUN critic to generate it
    2. For each critique:
       a. Check if grader run exists for the grader_model
       b. If not, RUN grader

    This ensures we have complete evaluation coverage for validation set terminal metrics.
    """
    init_db()
    critic_client = build_client(critic_model)
    grader_client = build_client(grader_model)

    # Phase 1: Find all work items (snapshot, scope, prompt) combinations
    with get_session() as session:
        # Get all validation snapshots
        valid_snapshots = session.query(Snapshot).filter_by(split=Split.VALID).all()

        if not valid_snapshots:
            typer.echo("No validation snapshots found")
            return

        typer.echo(f"Found {len(valid_snapshots)} validation snapshots")

        # Get all prompts
        all_prompts = session.query(Prompt).all()

        if not all_prompts:
            typer.echo("No prompts found in database")
            return

        typer.echo(f"Found {len(all_prompts)} prompts\n")

        # Build list of all work items: (snapshot, scope, prompt, critique_id_or_none)
        # critique_id_or_none is None if critic needs to run, otherwise UUID if grader needs to run, or "skip"
        work_items: list[tuple[SnapshotSlug, str, str, UUID | None | str]] = []

        for snapshot in valid_snapshots:
            # Get full-specimen critic scopes for this snapshot
            full_specimen_scopes = [scope for scope in snapshot.critic_scopes if snapshot.is_full_specimen_scope(scope)]

            if not full_specimen_scopes:
                typer.echo(f"⚠ Snapshot {snapshot.slug} has no full-specimen scopes, skipping")
                continue

            typer.echo(f"Snapshot {snapshot.slug}: {len(full_specimen_scopes)} full-specimen scopes")

            for scope in full_specimen_scopes:
                for prompt in all_prompts:
                    # Check if critic run exists for (snapshot, scope, prompt)
                    critic_run = session.execute(
                        select(CriticRun).where(
                            CriticRun.snapshot_slug == snapshot.slug,  # type: ignore[arg-type]
                            CriticRun.files_hash == scope.files_hash,
                            CriticRun.prompt_sha256 == prompt.prompt_sha256,
                        )
                    ).scalar_one_or_none()

                    if critic_run is None:
                        # No critic run exists, need to run critic then grader
                        work_items.append((snapshot.slug, scope.files_hash, prompt.prompt_sha256, None))
                        continue

                    if critic_run.critique_id is None:
                        # Critic run exists but failed (no critique), skip
                        work_items.append((snapshot.slug, scope.files_hash, prompt.prompt_sha256, "skip"))
                        continue

                    # Check if grader run exists for this critique
                    grader_exists = session.execute(
                        select(GraderRun.id)
                        .where(GraderRun.critique_id == critic_run.critique_id, GraderRun.model == grader_model)
                        .limit(1)
                    ).first()

                    if not grader_exists:
                        # Critic exists, need to run grader
                        work_items.append(
                            (snapshot.slug, scope.files_hash, prompt.prompt_sha256, critic_run.critique_id)
                        )
                    else:
                        # Both exist, skip
                        work_items.append((snapshot.slug, scope.files_hash, prompt.prompt_sha256, "skip"))

        # Count work needed
        need_critic = sum(1 for _, _, _, cid in work_items if cid is None)
        need_grader_only = sum(1 for _, _, _, cid in work_items if isinstance(cid, UUID))
        skipped = sum(1 for _, _, _, cid in work_items if cid == "skip")

        typer.echo("\nWork summary:")
        typer.echo(f"  {need_critic} items need critic + grader")
        typer.echo(f"  {need_grader_only} items need grader only")
        typer.echo(f"  {skipped} items complete (skipped)")

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
        critique_id_or_none: UUID | None | str,
        index: int,
        total: int,
    ) -> tuple[str, bool, bool]:
        """Process one work item: run critic if needed, then grader.
        Returns (status, critic_success, grader_success)"""
        async with semaphore:
            if critique_id_or_none == "skip":
                return ("skip", True, True)

            critique_id = critique_id_or_none
            critic_success = True
            grader_success = True

            # Step 1: Run critic if needed
            if critique_id is None:
                try:
                    # Get scope files from DB
                    with get_session() as session:
                        scope = session.execute(
                            select(Snapshot)
                            .join(Snapshot.critic_scopes)
                            .where(
                                Snapshot.slug == snapshot_slug  # type: ignore[arg-type]
                            )
                        ).scalar_one()

                        matching_scope = next((s for s in scope.critic_scopes if s.files_hash == files_hash), None)
                        if not matching_scope:
                            raise RuntimeError(f"Scope not found for files_hash={files_hash}")

                        scope_files = matching_scope.files

                    # Hydrate snapshot and run critic
                    async with hydrator.hydrate(snapshot_slug) as hydrated:
                        critic_input = CriticInput(
                            snapshot_slug=snapshot_slug,
                            files=ExplicitFileScope(files=[str(f) for f in scope_files]),
                            prompt_sha256=prompt_sha256,
                        )

                        _critic_output, _critic_run_id, critique_id = await run_critic(
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
                                f"[{index}/{total}] ✓ Critic {snapshot_slug} x {prompt_sha256[:8]} → {str(critique_id)[:8]}"
                            )
                except Exception as e:
                    typer.echo(
                        f"[{index}/{total}] ✗ Critic failed {snapshot_slug} x {prompt_sha256[:8]}: {e}", err=True
                    )
                    return ("critic_failed", False, False)

            # At this point, critique_id must be a UUID (str case was handled by early return)
            assert isinstance(critique_id, UUID)

            # Step 2: Run grader
            try:
                with get_session() as session:
                    grader_run_id = await grade_critique_by_id(
                        session, critique_id, grader_client, docker_client, verbose=verbose
                    )
                    if not verbose:
                        typer.echo(f"[{index}/{total}] ✓ Graded {str(critique_id)[:8]} → {str(grader_run_id)[:8]}")
            except Exception as e:
                typer.echo(f"[{index}/{total}] ✗ Grader failed {str(critique_id)[:8]}: {e}", err=True)
                return ("grader_failed", critic_success, False)

            return ("complete", critic_success, grader_success)

    # Filter out skipped items for processing
    items_to_process = [(s, f, p, c, i) for i, (s, f, p, c) in enumerate(work_items, 1) if c != "skip"]

    results = await asyncio.gather(
        *[
            process_one(snapshot, files_hash, prompt_sha256, critique_id, i, len(items_to_process))
            for i, (snapshot, files_hash, prompt_sha256, critique_id, _) in enumerate(items_to_process, 1)
        ]
    )

    # Summary
    complete = sum(1 for status, _, _ in results if status == "complete")
    critic_failures = sum(1 for status, _, _ in results if status == "critic_failed")
    grader_failures = sum(1 for status, _, _ in results if status == "grader_failed")

    typer.echo("\n=== Final Summary ===")
    typer.echo(f"Complete: {complete}")
    typer.echo(f"Critic failures: {critic_failures}")
    typer.echo(f"Grader failures: {grader_failures}")
