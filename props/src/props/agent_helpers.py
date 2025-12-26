"""Helpers for agents running inside the runtime container.

Provides:
- get_current_agent_run_id(): Get agent run ID from PostgreSQL RLS context
- get_scope_description(): Get critic scope description for template rendering
- fetch_snapshot(): Fetch snapshot to local filesystem and return path

For MCP client, use agent_container_util.mcp_client_from_env directly.

Database access: Just use get_session() directly - it auto-initializes from PG* env vars.

Usage:

    # Get agent run ID (from database - extracts from username pattern)
    from props.db.session import get_session
    from props.agent_helpers import get_current_agent_run_id

    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)

    # Database access (auto-initializes on first use)
    from props.db.session import get_session
    from props.db.models import Snapshot

    with get_session() as session:
        snapshots = session.query(Snapshot).filter_by(split='train').all()

    # MCP HTTP client (from agent_container_util.mcp)
    from agent_container_util.mcp import mcp_client_from_env

    async with mcp_client_from_env() as (client, _):
        result = await client.call_tool("tool_name", {"arg": "value"})
"""

from __future__ import annotations

import json
import logging
import subprocess
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from props.db.models import AgentRun
from props.db.session import get_session
from props.models.examples import WholeSnapshotExample

logger = logging.getLogger(__name__)


def get_current_agent_run_id(session: Session) -> UUID:
    """Get the current agent run ID from the database.

    Uses the PostgreSQL current_agent_run_id() function which extracts
    the UUID from the database username (e.g., agent_{uuid} pattern).

    This is the canonical way to get the current agent's run ID when running
    inside the container. The database extracts the ID from the agent user's
    username pattern.

    Args:
        session: Active SQLAlchemy session

    Returns:
        UUID of the current agent run

    Raises:
        RuntimeError: If not connected as an agent user, or if the
                      current_agent_run_id() function returns NULL
    """
    result = session.execute(text("SELECT current_agent_run_id()"))
    agent_run_id = result.scalar()
    if agent_run_id is None:
        raise RuntimeError(
            "current_agent_run_id() returned NULL - not connected as an agent user. "
            "Make sure you're using agent credentials (e.g., critic_agent_{uuid})."
        )
    if not isinstance(agent_run_id, UUID):
        agent_run_id = UUID(str(agent_run_id))
    return agent_run_id


def get_current_agent_run(session: Session) -> AgentRun:
    """Get the current agent run ORM object from the database.

    Combines get_current_agent_run_id() with loading the AgentRun record.
    Use this when you need the full AgentRun object with typed access to
    type_config via methods like prompt_optimizer_config().

    Args:
        session: Active SQLAlchemy session

    Returns:
        AgentRun object for the current agent

    Raises:
        RuntimeError: If not connected as an agent user
        ValueError: If agent run record not found in database

    Example:
        with get_session() as session:
            run = get_current_agent_run(session)
            config = run.prompt_optimizer_config()  # Type-safe access
            print(f"Target metric: {config.target_metric}")
    """
    agent_run_id = get_current_agent_run_id(session)
    agent_run = session.get(AgentRun, agent_run_id)
    if agent_run is None:
        raise ValueError(f"AgentRun not found for agent_run_id={agent_run_id}")
    return agent_run


def get_scope_description() -> str:
    """Get scope description for critic template.

    Returns a pre-formatted string describing the snapshot and files to review.
    Used as Jinja2 helper in critic.md.j2 template.
    """
    from props.db.models import FileSet

    with get_session() as session:
        agent_run = get_current_agent_run(session)
        example = agent_run.critic_config().example

        if isinstance(example, WholeSnapshotExample):
            return f"Snapshot: {example.snapshot_slug}\nReview: ALL files in snapshot"

        # SingleFileSetExample - look up files via FileSet (must exist)
        file_set = (
            session.query(FileSet).filter_by(snapshot_slug=example.snapshot_slug, files_hash=example.files_hash).one()
        )

        files = [member.file_path for member in file_set.members]
        files_str = ", ".join(files)

        return f"Snapshot: {example.snapshot_slug}\nFiles to review: {files_str}"


def fetch_snapshot(dest_dir: str) -> str:
    """Fetch snapshot for current critic agent to specified directory.

    Calls `props snapshot fetch <slug> <dest_dir>` to download snapshot.
    Used as Jinja2 helper in critic.md.j2 template.

    Args:
        dest_dir: Destination directory for the snapshot

    Returns:
        The dest_dir path (for template convenience)
    """
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        critic_config = agent_run.critic_config()
        snapshot_slug = critic_config.example.snapshot_slug

    # TODO: Calling CLI via subprocess is ugly - consider a direct Python API
    subprocess.run(["props", "snapshot", "fetch", snapshot_slug, dest_dir], check=True)
    return dest_dir


def get_agent_config() -> str:
    """Get JSON representation of current agent's type_config.

    Used as Jinja2 helper in critic_dev.md.j2 template.

    Returns:
        JSON string of type_config
    """
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        return json.dumps(agent_run.type_config, indent=2)


def get_grading_context() -> str:
    """Get grading context for grader template.

    Returns a pre-formatted string describing what the grader is evaluating:
    - The critic run being graded
    - The snapshot being graded

    RLS scoping details are documented in database_access.md (transcluded separately).

    Used as Jinja2 helper in grader.md.j2 template.
    """
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        grader_config = agent_run.grader_config()

        # Get the graded critic run to find snapshot info
        graded_run = session.get(AgentRun, grader_config.graded_agent_run_id)
        if graded_run is None:
            raise ValueError(f"Graded agent run not found: {grader_config.graded_agent_run_id}")

        # Get snapshot slug from critic's config
        critic_config = graded_run.critic_config()
        snapshot_slug = critic_config.example.snapshot_slug

        return f"""Graded Critic Run: {grader_config.graded_agent_run_id}
Snapshot: {snapshot_slug}"""
