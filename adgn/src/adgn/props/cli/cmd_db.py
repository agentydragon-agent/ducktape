"""Database management commands: sync, recreate."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg2 import sql
from rich.console import Console
from rich.table import Table
from sqlalchemy import create_engine, text
import typer

from adgn.cli_utils import async_run
from adgn.props.critic.prompts import list_critic_system_prompts
from adgn.props.db import get_session, recreate_database
from adgn.props.db.config import get_production_config
from adgn.props.db.prompts import load_and_upsert_detector_prompt_with_session
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


def sync_all() -> FullSyncResult:
    """Sync snapshots, issues, examples, detector prompts, and model metadata in a single operation.

    All sync operations happen within a single database session for consistency.

    Returns:
        Combined results from all sync operations
    """
    base_path = get_specimens_base_path()

    with get_session() as session:
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


def ensure_databases_exist() -> None:
    """Ensure eval_results database and agent_user role exist.

    Connects to the postgres database and creates application database if needed.
    Note: Tests create per-test databases (props_test_*), not a shared test database.
    """
    config = get_production_config()

    # Connect to postgres database to create application database
    postgres_config = config.with_database("postgres")
    engine = create_engine(postgres_config.admin_url(), isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        # Create eval_results database if it doesn't exist
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :dbname"), {"dbname": config.admin.database}
        )
        if not result.fetchone():
            typer.echo(f"  Creating database: {config.admin.database}")
            # Use psycopg2.sql for safe identifier quoting
            raw_conn = conn.connection
            cursor = raw_conn.cursor()
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config.admin.database)))
            cursor.close()

        # Create agent_user role if it doesn't exist
        result = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :rolname"), {"rolname": config.agent.user})
        if not result.fetchone():
            typer.echo(f"  Creating role: {config.agent.user}")
            # Use psycopg2.sql for safe identifier and literal quoting
            raw_conn = conn.connection
            cursor = raw_conn.cursor()
            cursor.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(config.agent.user), sql.Literal(config.agent.password)
                )
            )
            cursor.close()

    engine.dispose()


def recreate_database_and_sync() -> FullSyncResult:
    """Recreate database from scratch (destructive).

    Drops all tables/views/policies, creates fresh schema, and syncs all data
    (snapshots, issues, examples, detector prompts, and model metadata).

    Returns:
        Combined results from all sync operations
    """
    # Recreate schema (tables, RLS, roles)
    recreate_database()

    # Sync all data sources into fresh database
    return sync_all()


@async_run
async def cmd_sync() -> None:
    """Sync snapshots, issues, examples, detector prompts, and model metadata from source to DB."""
    console = Console()

    # Sync all data sources
    console.print("Syncing data from filesystem...")
    result = sync_all()

    # Data sync table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Type", style="cyan")
    table.add_column("Stats")
    table.add_row("Snapshots", result.snapshot_stats.summary_text)
    table.add_row("Issues", result.issue_stats.summary_text)
    table.add_row("Examples", result.example_stats.summary_text)
    table.add_row("Model metadata", result.model_metadata_stats.summary_text)
    console.print(table)

    # Detector prompts
    console.print("\nDetector prompts:")
    for detector in result.detector_prompts:
        console.print(f"  ✓ {detector.filename} → {detector.prompt_sha256[:12]}")


@async_run
async def cmd_db_recreate(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")) -> None:
    """Recreate database from scratch (destructive - drops all tables/views/policies).

    This command will:
    1. Ensure databases (eval_results, eval_results_test) exist
    2. Drop all existing tables, views, and RLS policies
    3. Create agent_user role (read-only with RLS)
    4. Create tables from ORM models
    5. Enable Row-Level Security policies
    6. Sync all data from filesystem (snapshots, issues, examples, detector prompts, model metadata)

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
    ensure_databases_exist()

    # Connect and recreate (includes full sync)
    console = Console()
    console.print("Recreating database schema...")
    result = recreate_database_and_sync()
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
