"""Database management commands: sync, recreate."""

from __future__ import annotations

import asyncio

import aiodocker
from props_core.db.config import DatabaseConfig, get_database_config
from props_core.db.session import get_session, recreate_database
from props_core.db.setup import ensure_database_exists
from props_core.db.sync.sync import FullSyncResult, build_definition_images, sync_all
from rich.console import Console
from rich.table import Table
import typer

# Database subcommand group
db_app = typer.Typer(help="Database management commands")


def ensure_databases_exist(config: DatabaseConfig) -> None:
    """Ensure eval_results database exists.

    Uses the unified helper from setup.py for database creation.
    Tests create per-test databases (props_test_*), not a shared test database.
    Note: agent_user role was deprecated - temporary users are now created per-agent instead.
    """
    ensure_database_exists(config, config.admin.database, drop_existing=False)


def recreate_database_and_sync(*, use_staged: bool = False) -> FullSyncResult:
    """Recreate database from scratch (destructive).

    Drops all tables/views/policies, creates fresh schema, and syncs all data
    (snapshots, issues, examples, model metadata, and agent definitions).

    Args:
        use_staged: If True, read agent definitions from staged files (index)
                    instead of HEAD. Skips the dirty check for development.

    Returns:
        Combined results from all sync operations
    """
    # Recreate schema (tables, RLS, roles)
    recreate_database()

    # Sync all data sources into fresh database
    with get_session() as session:
        return sync_all(session, use_staged=use_staged)


async def build_all_definition_images(console: Console) -> None:
    """Build Docker images for all agent definitions in the database."""
    async with aiodocker.Docker() as docker:
        with get_session() as session:
            count = await build_definition_images(docker, session)
    console.print(f"Built {count} agent definition images")


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
    table.add_row("Snapshot files", result.snapshot_file_stats.summary_text)
    table.add_row("File sets", result.file_set_stats.summary_text)
    table.add_row("Model metadata", result.model_metadata_stats.summary_text)
    table.add_row("Agent definitions", result.agent_definition_stats.summary_text)
    console.print(table)


def cmd_sync(
    use_staged: bool = typer.Option(
        False, "--use-staged", help="Read agent definitions from staged files instead of HEAD"
    ),
    build_images: bool = typer.Option(
        False, "--build-images", help="Build Docker images for all agent definitions after sync"
    ),
) -> None:
    """Sync snapshots, issues, files, file sets, model metadata, and agent definitions from source to DB."""
    console = Console()
    with get_session() as session:
        result = sync_all(session, use_staged=use_staged)
    print_sync_result(console, result)

    if build_images:
        asyncio.run(build_all_definition_images(console))


def cmd_db_recreate(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    use_staged: bool = typer.Option(
        False, "--use-staged", help="Read agent definitions from staged files instead of HEAD"
    ),
    build_images: bool = typer.Option(
        False, "--build-images", help="Build Docker images for all agent definitions after sync"
    ),
) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Ensure database exists (eval_results)
    2. Drop all existing schema objects (tables, views, RLS policies, functions)
    3. Run Alembic migrations to recreate schema
    4. Sync all data from filesystem (snapshots, issues, files, file sets, model metadata, agent definitions)
    5. (Optional) Build Docker images for all agent definitions

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
    result = recreate_database_and_sync(use_staged=use_staged)
    console.print("✓ Database recreated:")

    print_sync_result(console, result)

    if build_images:
        asyncio.run(build_all_definition_images(console))


# Register commands
db_app.command("sync")(cmd_sync)
db_app.command("recreate")(cmd_db_recreate)
