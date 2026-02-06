"""Runtime helpers for agents running inside containers.

Provides:
- get_current_agent_run_id(): Get agent run ID from PostgreSQL RLS context
- get_current_agent_run(): Get current agent run from database
- get_active_agent_run(): Get current agent run, ensuring it hasn't exited
- fetch_snapshot(): Fetch snapshot to local filesystem and return path
- setup_logging(): Configure logging for in-container agent loops
- render_system_prompt(): Render Jinja2 system prompt templates
- create_bound_model_from_env(): Create OpenAI model from env vars
"""

from __future__ import annotations

import importlib.resources
import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from jinja2 import Environment
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from openai_utils.model import BoundOpenAIModel
from props.agents.schema import describe_table
from props.db.database import Database
from props.db.models import AgentRun, AgentRunStatus
from props.db.queries import get_agent_run
from props.db.snapshot_io import fetch_snapshot_to_path

logger = logging.getLogger(__name__)

WORKSPACE = Path("/workspace")


# =============================================================================
# Agent run identification
# =============================================================================


def get_current_agent_run_id(session: Session) -> UUID:
    """Get agent run ID from PostgreSQL current_agent_run_id() function.

    Raises RuntimeError if not connected as an agent user.
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
    """Get the current agent run from database via RLS context."""
    agent_run_id = get_current_agent_run_id(session)
    return get_agent_run(session, agent_run_id)


def get_active_agent_run(session: Session) -> AgentRun:
    """Get the current agent run, ensuring it's still active (not already exited).

    Raises ValueError if the run has already exited.
    """
    agent_run = get_current_agent_run(session)
    if agent_run.status == AgentRunStatus.EXITED:
        raise ValueError(f"Agent run {agent_run.agent_run_id} already exited")
    return agent_run


# =============================================================================
# Snapshot fetching
# =============================================================================


def fetch_snapshot(dest_dir: Path, db: Database) -> Path:
    """Fetch snapshot for current critic agent to specified directory.

    Retrieves the tar archive from the snapshots table and extracts it
    to the specified directory.

    Returns:
        The dest_dir path (for template convenience)
    """
    with db.session() as session:
        agent_run = get_current_agent_run(session)
        critic_config = agent_run.critic_config()
        snapshot_slug = critic_config.example.snapshot_slug

    fetch_snapshot_to_path(snapshot_slug, dest_dir, db)
    return dest_dir


# =============================================================================
# Logging
# =============================================================================


def setup_logging() -> None:
    """Configure logging for in-container agent loops."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# =============================================================================
# Jinja2 template rendering
# =============================================================================


def _setup_jinja_env(db: Database, helpers: dict[str, Any] | None = None) -> Environment:
    """Create Jinja2 environment with standard helpers.

    Globals:
    - workspace_dir — default workspace path
    - describe_relation(name) — schema from SQLAlchemy metadata
    - include_doc(pkg/path) — include from package resources
    - include_file(path) — include from filesystem
    """
    env = Environment()
    env.globals["workspace_dir"] = str(WORKSPACE)

    def _describe_relation(name: str) -> str:
        desc = describe_table(name)
        if desc is None:
            return f"Unknown table: {name}"
        return desc.model_dump_json(indent=2, exclude_defaults=True)

    env.globals["describe_relation"] = _describe_relation

    def include_doc(pkg_path: str, *, raw: bool = False) -> str:
        """Include doc from package resources."""
        pkg, _, p = pkg_path.partition("/")
        content = (importlib.resources.files(pkg) / p).read_text()
        if raw:
            return f'<doc source="{pkg_path}">\n{content}\n</doc>'
        rendered = env.from_string(content).render()
        return f'<doc source="{pkg_path}">\n{rendered}\n</doc>'

    def include_file(file_path: str, *, raw: bool = False) -> str:
        """Include file from filesystem."""
        content = Path(file_path).read_text()
        if raw:
            return f'<doc source="{file_path}">\n{content}\n</doc>'
        rendered = env.from_string(content).render()
        return f'<doc source="{file_path}">\n{rendered}\n</doc>'

    env.globals["include_doc"] = include_doc
    env.globals["include_file"] = include_file

    if helpers:
        env.globals.update(helpers)

    return env


def render_system_prompt(template_path: str, db: Database, helpers: dict[str, Any] | None = None) -> str:
    """Render system prompt from package resource, returning as string.

    If PROMPT_TEMPLATE_PATH is set, reads the template from that filesystem path
    instead (used by variant images to override the default prompt).
    """
    prompt_override = os.environ.get("PROMPT_TEMPLATE_PATH")
    if prompt_override:
        logger.info("Using variant prompt from %s", prompt_override)
        content = Path(prompt_override).read_text()
    else:
        package, _, pkg_path = template_path.partition("/")
        resource = importlib.resources.files(package) / pkg_path
        content = resource.read_text()
    return render_template_string(content, db, helpers)


def render_template_string(content: str, db: Database, helpers: dict[str, Any] | None = None) -> str:
    """Render a Jinja2 template string with standard helpers."""
    env = _setup_jinja_env(db, helpers)
    return env.from_string(content).render()


# =============================================================================
# OpenAI model creation
# =============================================================================


def create_bound_model_from_env(db: Database) -> BoundOpenAIModel:
    """Create a BoundOpenAIModel using environment variables.

    Gets model from current agent run. Uses OPENAI_BASE_URL and OPENAI_API_KEY.
    """
    with db.session() as session:
        agent_run = get_current_agent_run(session)
        model = agent_run.model

    client = AsyncOpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])
    return BoundOpenAIModel(client=client, model=model)
