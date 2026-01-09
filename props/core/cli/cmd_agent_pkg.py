"""Agent package CLI commands.

Provides CLI access to agent package management:
- create: Pack directory into tar archive and insert into database
- fetch: Extract package from database and unpack to directory

Structure:
    props agent-pkg create <dir> [--id <id>] [--type <type>]
    props agent-pkg fetch <id> <target-dir>
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from sqlalchemy import text

from props.core.agent_pkg_utils import pack_agent_pkg, unpack_agent_pkg
from props.core.agent_types import AgentType
from props.core.db.models import AgentDefinition
from props.core.db.session import get_session

app = typer.Typer(name="agent-pkg", help="Agent package management commands", add_completion=False)


@app.command("create")
def cmd_create(
    pkg_dir: Annotated[Path, typer.Argument(help="Directory containing agent package")],
    pkg_id: Annotated[str | None, typer.Option("--id", help="Package ID (auto-generated if not provided)")] = None,
    agent_type: Annotated[AgentType, typer.Option("--type", help="Agent type")] = AgentType.FREEFORM,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing package")] = False,
) -> None:
    """Pack directory into tar archive and insert into agent_definitions table.

    Validates Dockerfile presence. /init is validated in the built image.
    Auto-generates ID from type + UUID if not provided.
    """
    # Generate ID if not provided
    if pkg_id is None:
        pkg_id = f"{agent_type}_{uuid4().hex[:8]}"

    # Pack and validate (raises NotADirectoryError/AgentPkgValidationError on failure)
    archive = pack_agent_pkg(pkg_dir)
    typer.echo(f"Packed {len(archive):,} bytes from {pkg_dir}")

    # Insert into database
    with get_session() as session:
        existing = session.get(AgentDefinition, pkg_id)
        if existing:
            if force:
                session.delete(existing)
                session.flush()
                typer.echo(f"Deleted existing package: {pkg_id}")
            else:
                typer.echo(f"Error: Package already exists: {pkg_id}", err=True)
                typer.echo("Use --force to overwrite", err=True)
                raise typer.Exit(1)

        # Get agent run ID if running inside an agent context (None for admin users)
        result = session.execute(text("SELECT current_agent_run_id()"))
        agent_run_id = result.scalar()

        definition = AgentDefinition(
            id=pkg_id, agent_type=agent_type, archive=archive, created_by_agent_run_id=agent_run_id
        )
        session.add(definition)
        session.commit()

    typer.echo(f"Created agent package: {pkg_id}")


@app.command("fetch")
def cmd_fetch(
    pkg_id: Annotated[str, typer.Argument(help="Package ID to fetch")],
    target_dir: Annotated[Path, typer.Argument(help="Target directory to unpack to")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing directory")] = False,
) -> None:
    """Extract package from database and unpack to target directory."""
    if target_dir.exists():
        if force:
            shutil.rmtree(target_dir)
            typer.echo(f"Removed existing directory: {target_dir}")
        else:
            typer.echo(f"Error: Target directory already exists: {target_dir}", err=True)
            typer.echo("Use --force to overwrite", err=True)
            raise typer.Exit(1)

    with get_session() as session:
        definition = session.get(AgentDefinition, pkg_id)
        if not definition:
            typer.echo(f"Error: Package not found: {pkg_id}", err=True)
            raise typer.Exit(1)

        archive = definition.archive
        agent_type = definition.agent_type

    unpack_agent_pkg(archive, target_dir)
    typer.echo(f"Unpacked {pkg_id} ({agent_type}) to {target_dir}")


@app.command("list")
def cmd_list(
    agent_type: Annotated[AgentType | None, typer.Option("--type", help="Filter by agent type")] = None,
) -> None:
    """List all agent packages in database."""
    with get_session() as session:
        query = session.query(AgentDefinition)
        if agent_type:
            query = query.filter_by(agent_type=agent_type)
        definitions = query.order_by(AgentDefinition.created_at.desc()).all()

        if not definitions:
            typer.echo("No agent packages found")
            return

        typer.echo(f"Found {len(definitions)} agent packages:\n")
        for defn in definitions:
            created_by = f" (by {defn.created_by_agent_run_id})" if defn.created_by_agent_run_id else ""
            typer.echo(f"  {defn.id} [{defn.agent_type}] {len(defn.archive):,} bytes{created_by}")


@app.command("validate")
def cmd_validate(pkg_dir: Annotated[Path, typer.Argument(help="Directory containing agent package")]) -> None:
    """Validate agent package structure without inserting into database.

    Checks Dockerfile presence. /init is validated in the built image.
    Exits with code 0 if valid, 1 if invalid.
    """
    # Pack with validation (raises NotADirectoryError/AgentPkgValidationError on failure)
    pack_agent_pkg(pkg_dir)
    typer.echo(f"Valid agent package: {pkg_dir}")
