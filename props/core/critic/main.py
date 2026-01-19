"""Critic agent main entry point for in-container execution.

This is the CMD entrypoint for the critic container. It:
1. Fetches the snapshot to /workspace
2. Renders the system prompt
3. Runs the agent loop until submit succeeds or failure
4. Exits with appropriate code
"""

from __future__ import annotations

import importlib.resources
import logging
import os
import sys
from io import StringIO
from pathlib import Path

from jinja2 import Environment

from props.core.agent_helpers import fetch_snapshot, get_current_agent_run, get_scope_description
from props.core.critic.loop import run_critic_loop_sync
from props.core.db.session import get_session

logger = logging.getLogger(__name__)

WORKSPACE = Path("/workspace")


def _setup_jinja_env(helpers: dict | None = None) -> Environment:
    """Create Jinja2 environment with standard helpers."""
    env = Environment()
    env.globals["workspace_dir"] = str(WORKSPACE)

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


def render_system_prompt(template_path: str, helpers: dict | None = None) -> str:
    """Render system prompt from package resource, returning as string.

    Args:
        template_path: Package path like "props/docs/agents/critic.md.j2"
        helpers: Optional dict of additional Jinja2 helpers

    Returns:
        Rendered system prompt
    """
    package, _, pkg_path = template_path.partition("/")
    resource = importlib.resources.files(package) / pkg_path
    root_content = resource.read_text()

    env = _setup_jinja_env(helpers)
    template = env.from_string(root_content)
    return template.render()


def main() -> int:
    """Main entry point for critic agent.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Critic agent starting")

    # Get model from agent run
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        model = agent_run.model
        logger.info("Agent run: %s, model: %s", agent_run.agent_run_id, model)

    # Fetch snapshot
    logger.info("Fetching snapshot to %s", WORKSPACE)
    fetch_snapshot(WORKSPACE)

    # Render system prompt
    logger.info("Rendering system prompt")
    system_prompt = render_system_prompt(
        "props/docs/agents/critic.md.j2",
        helpers={"scope_description": get_scope_description()},
    )

    # Run the agent loop
    logger.info("Starting agent loop")
    exit_code = run_critic_loop_sync(system_prompt, model)

    logger.info("Agent loop finished with exit code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
