"""Database management commands: sync, recreate."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table
import typer

from adgn.cli_utils import async_run
from adgn.props.critic.prompts import list_critic_system_prompts
from adgn.props.db import get_session, recreate_database
from adgn.props.db.config import DatabaseConfig, get_database_config
from adgn.props.db.prompts import load_and_upsert_detector_prompt_with_session
from adgn.props.db.setup import ensure_database_exists
from adgn.props.db.sync import (
    ModelMetadataSyncStats,
    SyncStats,
    get_specimens_base_path,
    sync_examples_to_db,
    sync_issues_to_db,
    sync_model_metadata_with_session,
    sync_snapshots_to_db,
)

# Database subcommand group
db_app = typer.Typer(help="Database management commands")


@dataclass
class DetectorPromptSyncResult:
    """Result from syncing a single detector prompt."""

    filename: str
    prompt_sha256: str


@dataclass
class FullSyncResult:
    """Combined result from syncing snapshots, issues, examples, detector prompts, and model metadata."""

    snapshot_stats: SyncStats
    issue_stats: SyncStats
    example_stats: SyncStats
    detector_prompts: list[DetectorPromptSyncResult]
    model_metadata_stats: ModelMetadataSyncStats


def sync_all(skip_specimens: bool = False) -> FullSyncResult:
    """Sync snapshots, issues, examples, detector prompts, and model metadata in a single operation.

    All sync operations happen within a single database session for consistency.

    Args:
        skip_specimens: If True, skip syncing all data from specimens repository
                       (snapshots, issues, examples)

    Returns:
        Combined results from all sync operations
    """
    with get_session() as session:
        if skip_specimens:
            # Skip all specimen data sync
            snapshot_stats = SyncStats(total=0, added=0, updated=0, deleted=0)
            issue_stats = SyncStats(total=0, added=0, updated=0, deleted=0)
            example_stats = SyncStats(total=0, added=0, updated=0, deleted=0)
        else:
            base_path = get_specimens_base_path()
            snapshot_stats = sync_snapshots_to_db(session, base_path)
            issue_stats = sync_issues_to_db(session, base_path)
            example_stats = sync_examples_to_db(session, base_path)

        # Sync critic system prompts
        detector_prompts = [
            DetectorPromptSyncResult(
                filename=filename, prompt_sha256=load_and_upsert_detector_prompt_with_session(session, filename)
            )
            for filename in list_critic_system_prompts()
        ]

        # Sync model metadata
        model_metadata_stats = sync_model_metadata_with_session(session)

        return FullSyncResult(
            snapshot_stats=snapshot_stats,
            issue_stats=issue_stats,
            example_stats=example_stats,
            detector_prompts=detector_prompts,
            model_metadata_stats=model_metadata_stats,
        )


def ensure_databases_exist(config: DatabaseConfig) -> None:
    """Ensure eval_results database exists.

    Uses the unified helper from setup.py for database creation.
    Tests create per-test databases (props_test_*), not a shared test database.
    Note: agent_user role was deprecated - temporary users are now created per-agent instead.
    """
    ensure_database_exists(config, config.admin.database, drop_existing=False)


def recreate_database_and_sync(skip_specimens: bool = False) -> FullSyncResult:
    """Recreate database from scratch (destructive).

    Drops all tables/views/policies, creates fresh schema, and syncs all data
    (snapshots, issues, examples, detector prompts, and model metadata).

    Args:
        skip_specimens: If True, skip syncing all data from specimens repository

    Returns:
        Combined results from all sync operations
    """
    # Recreate schema (tables, RLS, roles)
    recreate_database()

    # Sync all data sources into fresh database
    return sync_all(skip_specimens=skip_specimens)


@async_run
async def cmd_sync(
    skip_specimens: bool = typer.Option(False, "--skip-specimens", help="Skip syncing from specimens repository"),
) -> None:
    """Sync snapshots, issues, examples, detector prompts, and model metadata from source to DB."""
    console = Console()

    # Sync all data sources
    if skip_specimens:
        console.print("Syncing data (skipping specimens repository)...")
    else:
        console.print("Syncing data from filesystem...")
    result = sync_all(skip_specimens=skip_specimens)

    # Data sync table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Type", style="cyan")
    table.add_column("Stats")
    table.add_row("Snapshots", result.snapshot_stats.summary_text)
    table.add_row("Issues", result.issue_stats.summary_text)
    table.add_row("Examples", result.example_stats.summary_text)
    table.add_row("Model metadata", result.model_metadata_stats.summary_text)
    console.print(table)

    # Detector prompts (critic system prompts synced to DB)
    console.print("\n[bold]Critic prompts (file → sha256):[/bold]")
    for detector in result.detector_prompts:
        console.print(f"  {detector.filename} → {detector.prompt_sha256}")


@async_run
async def cmd_db_recreate(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    skip_specimens: bool = typer.Option(False, "--skip-specimens", help="Skip syncing from specimens repository"),
) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Ensure database exists (eval_results)
    2. Drop all existing schema objects (tables, views, RLS policies, functions)
    3. Run Alembic migrations to recreate schema
    4. Sync all data from filesystem (snapshots, issues, examples, detector prompts, model metadata)

    Note: Temporary database users are created per-agent instead of a shared agent_user role.
          Schema creation (step 3) runs all Alembic migrations, which define tables, views, RLS, etc.

    Requires database connection configured via environment variables (postgres superuser).
    """
    if not yes:
        typer.echo("⚠️  WARNING: This will DELETE ALL data in the database!")
        confirm = typer.prompt("Type 'yes' to confirm")
        if confirm != "yes":
            typer.echo("Aborted")
            raise typer.Exit(1)

    # Ensure databases exist before trying to connect
    typer.echo("Ensuring databases exist...")
    db_config = get_database_config()
    ensure_databases_exist(db_config)

    # Connect and recreate (includes full sync)
    console = Console()
    console.print("Recreating database schema...")
    if skip_specimens:
        console.print("(Skipping specimens repository sync)")
    result = recreate_database_and_sync(skip_specimens=skip_specimens)
    console.print("✓ Database recreated:")

    # Data sync table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Type", style="cyan")
    table.add_column("Stats")
    table.add_row("Snapshots", result.snapshot_stats.summary_text)
    table.add_row("Issues", result.issue_stats.summary_text)
    table.add_row("Examples", result.example_stats.summary_text)
    table.add_row("Model metadata", result.model_metadata_stats.summary_text)
    table.add_row("Detector prompts", f"{len(result.detector_prompts)} synced")
    console.print(table)


# Register commands
db_app.command("sync")(cmd_sync)
db_app.command("recreate")(cmd_db_recreate)
