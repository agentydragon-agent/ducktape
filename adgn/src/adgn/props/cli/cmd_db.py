"""Database management commands: sync, recreate."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table
import typer

from adgn.cli_utils import async_run
from adgn.props.db import get_session, recreate_database
from adgn.props.db.config import DatabaseConfig, get_database_config
from adgn.props.db.setup import ensure_database_exists
from adgn.props.db.sync import (
    ModelMetadataSyncStats,
    SyncStats,
    get_specimens_base_path,
    sync_agent_definitions_to_db,
    sync_examples_to_db,
    sync_issues_to_db,
    sync_model_metadata_with_session,
    sync_snapshots_to_db,
)

# Database subcommand group
db_app = typer.Typer(help="Database management commands")


@dataclass
class FullSyncResult:
    """Combined result from syncing snapshots, issues, examples, model metadata, and agent definitions."""

    snapshot_stats: SyncStats
    issue_stats: SyncStats
    example_stats: SyncStats
    model_metadata_stats: ModelMetadataSyncStats
    agent_definition_stats: SyncStats


def sync_all() -> FullSyncResult:
    """Sync snapshots, issues, examples, model metadata, and agent definitions in a single operation.

    All sync operations happen within a single database session for consistency.

    Returns:
        Combined results from all sync operations
    """
    with get_session() as session:
        base_path = get_specimens_base_path()
        snapshot_stats = sync_snapshots_to_db(session, base_path)
        issue_stats = sync_issues_to_db(session, base_path)
        example_stats = sync_examples_to_db(session, base_path)

        # Sync model metadata
        model_metadata_stats = sync_model_metadata_with_session(session)

        # Sync repo-tracked agent definitions
        agent_definition_stats = sync_agent_definitions_to_db(session)

        return FullSyncResult(
            snapshot_stats=snapshot_stats,
            issue_stats=issue_stats,
            example_stats=example_stats,
            model_metadata_stats=model_metadata_stats,
            agent_definition_stats=agent_definition_stats,
        )


def ensure_databases_exist(config: DatabaseConfig) -> None:
    """Ensure eval_results database exists.

    Uses the unified helper from setup.py for database creation.
    Tests create per-test databases (props_test_*), not a shared test database.
    Note: agent_user role was deprecated - temporary users are now created per-agent instead.
    """
    ensure_database_exists(config, config.admin.database, drop_existing=False)


def recreate_database_and_sync() -> FullSyncResult:
    """Recreate database from scratch (destructive).

    Drops all tables/views/policies, creates fresh schema, and syncs all data
    (snapshots, issues, examples, model metadata, and agent definitions).

    Returns:
        Combined results from all sync operations
    """
    # Recreate schema (tables, RLS, roles)
    recreate_database()

    # Sync all data sources into fresh database
    return sync_all()


def print_sync_result(console: Console, result: FullSyncResult) -> None:
    """Print sync result summary table.

    Args:
        console: Rich console for output
        result: Sync result to display
    """
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Type", style="cyan")
    table.add_column("Stats")
    table.add_row("Snapshots", result.snapshot_stats.summary_text)
    table.add_row("Issues", result.issue_stats.summary_text)
    table.add_row("Examples", result.example_stats.summary_text)
    table.add_row("Model metadata", result.model_metadata_stats.summary_text)
    table.add_row("Agent definitions", result.agent_definition_stats.summary_text)
    console.print(table)


@async_run
async def cmd_sync() -> None:
    """Sync snapshots, issues, examples, model metadata, and agent definitions from source to DB."""
    console = Console()
    console.print("Syncing data from filesystem...")
    result = sync_all()
    print_sync_result(console, result)


@async_run
async def cmd_db_recreate(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Ensure database exists (eval_results)
    2. Drop all existing schema objects (tables, views, RLS policies, functions)
    3. Run Alembic migrations to recreate schema
    4. Sync all data from filesystem (snapshots, issues, examples, model metadata, agent definitions)

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
    result = recreate_database_and_sync()
    console.print("✓ Database recreated:")

    print_sync_result(console, result)


# Register commands
db_app.command("sync")(cmd_sync)
db_app.command("recreate")(cmd_db_recreate)
