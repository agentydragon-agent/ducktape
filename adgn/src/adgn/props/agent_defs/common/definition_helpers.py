"""Helpers for agents that create or manipulate agent definitions.

These helpers are available to agents running in containers (prompt_optimizer,
improvement) for downloading, unpacking, and creating agent definitions.
"""

from pathlib import Path
from uuid import uuid4

from adgn.props.db import get_session
from adgn.props.db.models import AgentDefinition
from adgn.props.definition_utils import pack_definition, unpack_definition, validate_definition


def download_definition(definition_id: str, target_dir: Path) -> None:
    """Download and unpack an agent definition to a directory.

    Args:
        definition_id: ID of the definition to download (e.g., "critic", "grader")
        target_dir: Directory to unpack into (created if needed)

    Raises:
        ValueError: If definition not found

    Example:
        download_definition("critic", Path("/workspace/base_critic"))
        # Now /workspace/base_critic contains:
        #   AGENT.md, init, bin/, docs/, etc.
    """
    with get_session() as session:
        definition = session.get(AgentDefinition, definition_id)
        if not definition:
            raise ValueError(f"Agent definition not found: {definition_id}")
        unpack_definition(definition.archive, target_dir)


def list_definitions() -> list[tuple[str, str]]:
    """List all available agent definitions.

    Returns:
        List of (definition_id, agent_type) tuples

    Example:
        for def_id, agent_type in list_definitions():
            print(f"{def_id}: {agent_type}")
    """
    with get_session() as session:
        definitions = session.query(AgentDefinition).all()
        return [(d.id, d.agent_type) for d in definitions]


def create_definition(
    definition_dir: Path, agent_type: str = "critic", created_by_agent_run_id: str | None = None
) -> str:
    """Validate, pack, and insert a new agent definition.

    The definition directory must contain:
    - AGENT.md: System prompt
    - init: Executable bootstrap script (chmod +x)

    Security: External symlinks are rejected (resolve_symlinks=False).
    All files must be explicitly included in the definition directory.

    Args:
        definition_dir: Path to definition directory
        agent_type: Type of agent (e.g., "critic", "grader")
        created_by_agent_run_id: UUID of the agent run that created this (optional)

    Returns:
        The generated definition ID

    Raises:
        ValueError: If definition is invalid or contains external symlinks

    Example:
        # Create definition directory with required files
        my_dir = Path("/workspace/my_critic")
        my_dir.mkdir()
        (my_dir / "AGENT.md").write_text("# My Custom Critic\\n...")
        init = my_dir / "init"
        init.write_text("#!/usr/bin/env python3\\nprint('ready')")
        init.chmod(0o755)

        # Create and insert
        def_id = create_definition(my_dir, agent_type="critic")
        print(f"Created: {def_id}")
    """
    # Validate structure
    errors = validate_definition(definition_dir)
    if errors:
        error_list = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(f"Invalid agent definition:\n{error_list}")

    # Pack (resolve_symlinks=False for security - rejects external symlinks)
    archive = pack_definition(definition_dir, resolve_symlinks=False)

    # Generate ID
    definition_id = f"{agent_type}_{uuid4().hex[:12]}"

    # Insert into database
    with get_session() as session:
        definition = AgentDefinition(
            id=definition_id, agent_type=agent_type, archive=archive, created_by_agent_run_id=created_by_agent_run_id
        )
        session.add(definition)
        session.commit()

    return definition_id
