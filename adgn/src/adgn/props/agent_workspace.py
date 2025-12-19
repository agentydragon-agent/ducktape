"""Agent workspace path utilities.

Agent workspaces are persistent directories that store:
- Unpacked agent definition (AGENT.md, init, tools/, etc.)
- Files created by the agent during operation

Workspaces are stored at a predictable path derived from agent_run_id,
allowing them to survive container restarts and app quits.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

# Default base directory for agent workspaces
# Can be overridden via ADGN_WORKSPACES_DIR environment variable
DEFAULT_WORKSPACES_BASE = Path.home() / ".local" / "share" / "adgn" / "workspaces"


def get_workspaces_base() -> Path:
    """Get the base directory for agent workspaces.

    Returns:
        Path to workspaces base directory. Uses ADGN_WORKSPACES_DIR env var
        if set, otherwise ~/.local/share/adgn/workspaces/
    """
    env_path = os.environ.get("ADGN_WORKSPACES_DIR")
    if env_path:
        return Path(env_path)
    return DEFAULT_WORKSPACES_BASE


def get_workspace_path(agent_run_id: UUID) -> Path:
    """Get the workspace path for an agent run.

    The workspace path is deterministic based on agent_run_id, enabling:
    - Persistence across container restarts
    - Resume after app quits
    - Predictable cleanup

    Args:
        agent_run_id: The agent's unique run identifier

    Returns:
        Path to the agent's workspace directory (host path, mounted as
        /workspace in container). Directory may or may not exist yet.

    Example:
        >>> get_workspace_path(UUID("550e8400-e29b-41d4-a716-446655440000"))
        PosixPath('/home/user/.local/share/adgn/workspaces/550e8400-e29b-41d4-a716-446655440000')
    """
    return get_workspaces_base() / str(agent_run_id)
