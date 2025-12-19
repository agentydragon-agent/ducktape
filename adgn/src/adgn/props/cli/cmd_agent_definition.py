"""Agent definition CLI commands.

Provides CLI access to agent definition management:
- create: Pack directory into tar archive and insert into database
- fetch: Extract definition from database and unpack to directory

Structure:
    adgn-properties agent-definition create <dir> [--id <id>] [--type <type>]
    adgn-properties agent-definition fetch <id> <target-dir>
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import shutil
import tarfile
from typing import Annotated

import typer

from adgn.props.agent_types import AgentType
from adgn.props.db import get_session
from adgn.props.db.models import AgentDefinition

app = typer.Typer(name="agent-definition", help="Agent definition management commands", add_completion=False)


def _compute_definition_hash(definition_dir: Path) -> str:
    """Compute SHA256 of agent definition directory for auto-ID generation.

    Hash includes relative paths, executable flags, and file contents.
    """
    hasher = hashlib.sha256()
    for path in sorted(definition_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(definition_dir)
            mode = "x" if os.access(path, os.X_OK) else "r"
            hasher.update(f"{rel}:{mode}:".encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _pack_definition(definition_dir: Path) -> bytes:
    """Pack directory into uncompressed tar archive."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in sorted(definition_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(definition_dir)
                tar.add(path, arcname=str(rel))
    return buffer.getvalue()


def _unpack_definition(archive: bytes, target_dir: Path) -> None:
    """Unpack tar archive to target directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO(archive)
    with tarfile.open(fileobj=buffer, mode="r") as tar:
        tar.extractall(target_dir)


def _validate_definition(definition_dir: Path) -> list[str]:
    """Validate agent definition structure, return list of errors."""
    errors = []

    # AGENT.md required
    agent_md = definition_dir / "AGENT.md"
    if not agent_md.exists():
        errors.append("Missing required file: AGENT.md")

    # init required and must be executable
    init_script = definition_dir / "init"
    if not init_script.exists():
        errors.append("Missing required file: init")
    elif not os.access(init_script, os.X_OK):
        errors.append("init script must be executable (chmod +x)")

    return errors


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
    Auto-generates ID from type + hash prefix if not provided.
    """
    # Validate directory exists
    if not definition_dir.is_dir():
        typer.echo(f"Error: {definition_dir} is not a directory", err=True)
        raise typer.Exit(1)

    # Validate structure
    errors = _validate_definition(definition_dir)
    if errors:
        typer.echo("Validation errors:", err=True)
        for error in errors:
            typer.echo(f"  - {error}", err=True)
        raise typer.Exit(1)

    # Generate ID if not provided
    if definition_id is None:
        content_hash = _compute_definition_hash(definition_dir)
        definition_id = f"{agent_type.value}_{content_hash[:8]}"

    # Pack definition
    archive = _pack_definition(definition_dir)
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

        definition = AgentDefinition(
            id=definition_id,
            agent_type=agent_type.value,
            archive=archive,
            created_by_agent_run_id=None,  # CLI-created, not agent-created
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
    # Check target directory
    if target_dir.exists():
        if force:
            shutil.rmtree(target_dir)
            typer.echo(f"Removed existing directory: {target_dir}")
        else:
            typer.echo(f"Error: Target directory already exists: {target_dir}", err=True)
            typer.echo("Use --force to overwrite", err=True)
            raise typer.Exit(1)

    # Fetch from database
    with get_session() as session:
        definition = session.get(AgentDefinition, definition_id)
        if not definition:
            typer.echo(f"Error: Definition not found: {definition_id}", err=True)
            raise typer.Exit(1)

        archive = definition.archive
        agent_type = definition.agent_type

    # Unpack
    _unpack_definition(archive, target_dir)
    typer.echo(f"Unpacked {definition_id} ({agent_type}) to {target_dir}")


@app.command("list")
def cmd_list(
    agent_type: Annotated[AgentType | None, typer.Option("--type", help="Filter by agent type")] = None,
) -> None:
    """List all agent definitions in database."""
    with get_session() as session:
        query = session.query(AgentDefinition)
        if agent_type:
            query = query.filter_by(agent_type=agent_type.value)
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
    # Validate directory exists
    if not definition_dir.is_dir():
        typer.echo(f"Error: {definition_dir} is not a directory", err=True)
        raise typer.Exit(1)

    # Run validation
    errors = _validate_definition(definition_dir)
    if errors:
        typer.echo("Validation failed:", err=True)
        for error in errors:
            typer.echo(f"  ✗ {error}", err=True)
        raise typer.Exit(1)

    typer.echo(f"✓ Valid agent definition: {definition_dir}")
