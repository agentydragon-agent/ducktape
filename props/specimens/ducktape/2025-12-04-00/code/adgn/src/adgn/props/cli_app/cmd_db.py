"""Database management commands: sync, db-recreate."""

from __future__ import annotations

from dataclasses import dataclass

import typer

from adgn.props.cli_app.decorators import async_run
from adgn.props.db import get_session, init_db, recreate_database
from adgn.props.db.prompts import discover_detector_prompts, load_and_upsert_detector_prompt
from adgn.props.db.sync import SyncStats, sync_issues_to_db, sync_snapshots_to_db
from adgn.props.db.sync_model_metadata import ModelMetadataSyncStats, sync_model_metadata
from adgn.props.snapshot_registry import SnapshotRegistry


@dataclass
class DetectorPromptSyncResult:
    """Result from syncing a single detector prompt."""

    filename: str
    prompt_sha256: str


@dataclass
class FullSyncResult:
    """Combined result from syncing snapshots, issues, detector prompts, and model metadata."""

    snapshot_stats: SyncStats
    issue_stats: SyncStats
    detector_prompts: list[DetectorPromptSyncResult]
    model_metadata_stats: ModelMetadataSyncStats


def sync_detector_prompts() -> list[DetectorPromptSyncResult]:
    """Sync all detector prompts from prompts/system/*.md to database.

    Returns:
        List of synced detector prompts with their SHA-256 hashes
    """
    return [
        DetectorPromptSyncResult(filename=filename, prompt_sha256=load_and_upsert_detector_prompt(filename))
        for filename in discover_detector_prompts()
    ]


def sync_all() -> FullSyncResult:
    """Sync snapshots, issues, detector prompts, and model metadata in a single operation.

    Returns:
        Combined results from all sync operations
    """
    registry = SnapshotRegistry.from_package_resources()
    with get_session() as session:
        snapshot_stats = sync_snapshots_to_db(session, registry)
        issue_stats = sync_issues_to_db(session, registry)

    return FullSyncResult(
        snapshot_stats=snapshot_stats,
        issue_stats=issue_stats,
        detector_prompts=sync_detector_prompts(),
        model_metadata_stats=sync_model_metadata(),
    )


def recreate_database_schema() -> tuple[SyncStats, SyncStats]:
    """Recreate database from scratch (destructive).

    Drops all tables/views/policies, creates fresh schema, and syncs snapshots/issues.

    Returns:
        Tuple of (snapshot_stats, issue_stats) after recreation
    """
    # Recreate schema (tables, RLS, roles)
    recreate_database()

    # Sync snapshots and issues into fresh database
    registry = SnapshotRegistry.from_package_resources()
    with get_session() as session:
        snapshot_stats = sync_snapshots_to_db(session, registry)
        issue_stats = sync_issues_to_db(session, registry)

    return snapshot_stats, issue_stats


@async_run
async def cmd_sync() -> None:
    """Sync snapshots, issues, detector prompts, and model metadata from source to DB."""
    init_db()

    # Sync all data sources
    typer.echo("Syncing snapshots and issues...")
    result = sync_all()

    typer.echo(f"  Snapshots: {result.snapshot_stats.summary_text}")
    typer.echo(f"  Issues:    {result.issue_stats.summary_text}")

    typer.echo("\nSyncing detector prompts...")
    for detector in result.detector_prompts:
        typer.echo(f"  ✓ {detector.filename:50} → {detector.prompt_sha256[:12]}")

    typer.echo("\nSyncing model metadata...")
    typer.echo(f"  {result.model_metadata_stats.summary_text}")


@async_run
async def cmd_db_recreate(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Drop all existing tables, views, and RLS policies
    2. Create agent_user role (read-only with RLS)
    3. Create tables from ORM models
    4. Enable Row-Level Security policies
    5. Sync snapshots and issues from filesystem

    Requires PROPS_DB_URL environment variable (postgres superuser connection).
    """
    if not yes:
        typer.echo("⚠️  WARNING: This will DELETE ALL data in the database!")
        confirm = typer.prompt("Type 'yes' to confirm")
        if confirm != "yes":
            typer.echo("Aborted")
            raise typer.Exit(1)

    # Connect and recreate (includes snapshot/issue sync)
    init_db()
    typer.echo("Recreating database schema...")
    snapshot_stats, issue_stats = recreate_database_schema()
    typer.echo("✓ Database recreated:")
    typer.echo(f"  Snapshots: {snapshot_stats.summary_text}")
    typer.echo(f"  Issues:    {issue_stats.summary_text}")
