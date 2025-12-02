"""Database management commands: sync-specimens, db-recreate."""

from __future__ import annotations

import typer

from adgn.props.cli_app.decorators import async_run
from adgn.props.db import init_db, recreate_database
from adgn.props.db.sync_specimens import sync_specimens


@async_run
async def cmd_sync_specimens() -> None:
    """Sync specimens table from splits.py (train/valid/test assignments).

    Ensures database exactly matches source of truth in splits.py.

    Requires PROPS_DB_URL environment variable (admin credentials).
    """
    init_db()

    typer.echo("Syncing specimens table...")
    stats = await sync_specimens()
    typer.echo(f"Sync complete: {stats.summary_text}")


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

    # Connect and recreate
    init_db()
    recreate_database()

    # Sync specimens
    typer.echo("Syncing specimens...")
    stats = await sync_specimens()
    typer.echo(f"✓ Database recreated with {stats.summary_text}")
