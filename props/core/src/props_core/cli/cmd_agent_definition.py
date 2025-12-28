"""Agent definition CLI commands.

Provides CLI access to agent definition management:
- create: Pack directory into tar archive and insert into database
- fetch: Extract definition from database and unpack to directory

Structure:
    props agent-definition create <dir> [--id <id>] [--type <type>]
    props agent-definition fetch <id> <target-dir>
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Annotated
from uuid import uuid4

from props_core.agent_types import AgentType
from props_core.db.models import AgentDefinition
from props_core.db.session import get_session
from props_core.definition_utils import pack_definition, unpack_definition
from sqlalchemy import text
import typer

app = typer.Typer(name="agent-definition", help="Agent definition management commands", add_completion=False)


@app.command("create")
def cmd_create(
    definition_dir: Annotated[Path, typer.Argument(help="Directory containing agent definition")],
    definition_id: Annotated[
        str | None, typer.Option("--id", help="Definition ID (auto-generated if not provided)")
    ] = None,
    agent_type: Annotated[AgentType, typer.Option("--type", help="Agent type")] = AgentType.FREEFORM,
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing definition")] = False,
) -> None:
    """Pack directory into tar archive and insert into agent_definitions table.

    Validates structure (AGENT.md required, init must be executable).
    Auto-generates ID from type + UUID if not provided.
    """
    # Generate ID if not provided
    if definition_id is None:
        definition_id = f"{agent_type}_{uuid4().hex[:8]}"

    # Pack and validate (raises NotADirectoryError/DefinitionValidationError on failure)
    archive = pack_definition(definition_dir)
    typer.echo(f"Packed {len(archive):,} bytes from {definition_dir}")

    # Insert into database
    with get_session() as session:
        existing = session.get(AgentDefinition, definition_id)
        if existing:
            if force:
                session.delete(existing)
                session.flush()
                typer.echo(f"Deleted existing definition: {definition_id}")
            else:
                typer.echo(f"Error: Definition already exists: {definition_id}", err=True)
                typer.echo("Use --force to overwrite", err=True)
                raise typer.Exit(1)

        # Get agent run ID if running inside an agent context (None for admin users)
        result = session.execute(text("SELECT current_agent_run_id()"))
        agent_run_id = result.scalar()

        definition = AgentDefinition(
            id=definition_id, agent_type=agent_type, archive=archive, created_by_agent_run_id=agent_run_id
        )
        session.add(definition)
        session.commit()

    typer.echo(f"Created agent definition: {definition_id}")


@app.command("fetch")
def cmd_fetch(
    definition_id: Annotated[str, typer.Argument(help="Definition ID to fetch")],
    target_dir: Annotated[Path, typer.Argument(help="Target directory to unpack to")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing directory")] = False,
) -> None:
    """Extract definition from database and unpack to target directory."""
    if target_dir.exists():
        if force:
            shutil.rmtree(target_dir)
            typer.echo(f"Removed existing directory: {target_dir}")
        else:
            typer.echo(f"Error: Target directory already exists: {target_dir}", err=True)
            typer.echo("Use --force to overwrite", err=True)
            raise typer.Exit(1)

    with get_session() as session:
        definition = session.get(AgentDefinition, definition_id)
        if not definition:
            typer.echo(f"Error: Definition not found: {definition_id}", err=True)
            raise typer.Exit(1)

        archive = definition.archive
        agent_type = definition.agent_type

    unpack_definition(archive, target_dir)
    typer.echo(f"Unpacked {definition_id} ({agent_type}) to {target_dir}")


@app.command("list")
def cmd_list(
    agent_type: Annotated[AgentType | None, typer.Option("--type", help="Filter by agent type")] = None,
) -> None:
    """List all agent definitions in database."""
    with get_session() as session:
        query = session.query(AgentDefinition)
        if agent_type:
            query = query.filter_by(agent_type=agent_type)
        definitions = query.order_by(AgentDefinition.created_at.desc()).all()

        if not definitions:
            typer.echo("No agent definitions found")
            return

        typer.echo(f"Found {len(definitions)} agent definitions:\n")
        for defn in definitions:
            created_by = f" (by {defn.created_by_agent_run_id})" if defn.created_by_agent_run_id else ""
            typer.echo(f"  {defn.id} [{defn.agent_type}] {len(defn.archive):,} bytes{created_by}")


@app.command("validate")
def cmd_validate(definition_dir: Annotated[Path, typer.Argument(help="Directory containing agent definition")]) -> None:
    """Validate agent definition structure without inserting into database.

    Checks:
    - AGENT.md exists
    - init script exists and is executable

    Exits with code 0 if valid, 1 if invalid.
    """
    # Pack with validation (raises NotADirectoryError/DefinitionValidationError on failure)
    pack_definition(definition_dir)
    typer.echo(f"Valid agent definition: {definition_dir}")
