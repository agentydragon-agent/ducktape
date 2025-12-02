"""Database management commands: sync, db-recreate."""

from __future__ import annotations

from dataclasses import dataclass

import typer

from adgn.props.cli_app.decorators import async_run
from adgn.props.db import init_db, recreate_database
from adgn.props.db.prompts import discover_detector_prompts, load_and_upsert_detector_prompt
from adgn.props.db.sync_model_pricing import ModelPricingSyncStats, sync_model_pricing
from adgn.props.db.sync_specimens import SyncStats, sync_specimens


@dataclass
class DetectorPromptSyncResult:
    """Result from syncing a single detector prompt."""

    filename: str
    prompt_sha256: str


@dataclass
class FullSyncResult:
    """Combined result from syncing specimens, detector prompts, and model pricing."""

    specimen_stats: SyncStats
    detector_prompts: list[DetectorPromptSyncResult]
    model_pricing_stats: ModelPricingSyncStats


def sync_detector_prompts() -> list[DetectorPromptSyncResult]:
    """Sync all detector prompts from prompts/system/*.md to database.

    Returns:
        List of synced detector prompts with their SHA-256 hashes
    """
    return [
        DetectorPromptSyncResult(filename=filename, prompt_sha256=load_and_upsert_detector_prompt(filename))
        for filename in discover_detector_prompts()
    ]


async def sync_all() -> FullSyncResult:
    """Sync specimens, detector prompts, and model pricing in a single operation.

    Returns:
        Combined results from all sync operations
    """
    return FullSyncResult(
        specimen_stats=await sync_specimens(),
        detector_prompts=sync_detector_prompts(),
        model_pricing_stats=sync_model_pricing(),
    )


async def recreate_database_schema() -> SyncStats:
    """Recreate database from scratch (destructive).

    Drops all tables/views/policies, creates fresh schema, and syncs specimens.

    Returns:
        Statistics about specimens synced after recreation
    """
    # Recreate schema (tables, RLS, roles)
    recreate_database()

    # Sync specimens into fresh database
    return await sync_specimens()


@async_run
async def cmd_sync() -> None:
    """Sync specimens, detector prompts, and model pricing from source to DB."""
    init_db()

    # Sync all data sources
    typer.echo("Syncing specimens...")
    result = await sync_all()

    typer.echo(f"  {result.specimen_stats.summary_text}")

    typer.echo("\nSyncing detector prompts...")
    for detector in result.detector_prompts:
        typer.echo(f"  ✓ {detector.filename:50} → {detector.prompt_sha256[:12]}")

    typer.echo("\nSyncing model pricing...")
    typer.echo(f"  {result.model_pricing_stats.summary_text}")


@async_run
async def cmd_db_recreate(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Drop all existing tables, views, and RLS policies
    2. Create agent_user role (read-only with RLS)
    3. Create tables from ORM models
    4. Enable Row-Level Security policies
    5. Sync specimens from splits.py

    Requires PROPS_DB_URL environment variable (postgres superuser connection).
    """
    if not yes:
        typer.echo("⚠️  WARNING: This will DELETE ALL data in the database!")
        confirm = typer.prompt("Type 'yes' to confirm")
        if confirm != "yes":
            typer.echo("Aborted")
            raise typer.Exit(1)

    # Connect and recreate (includes specimen sync)
    init_db()
    typer.echo("Recreating database schema...")
    stats = await recreate_database_schema()
    typer.echo(f"✓ Database recreated with {stats.summary_text}")
