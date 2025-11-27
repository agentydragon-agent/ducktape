"""Agent control MCP server.

Provides tools for controlling agent execution:
- send_prompt: Send a prompt to start an agent run
- abort_run: Abort the currently running agent

This server is only mounted for internal agents (not external).
External agents are controlled by their own environment.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from adgn.agent.runtime.container import AgentContainer

logger = logging.getLogger(__name__)


def make_agent_control_server(
    name: str,
    container: "AgentContainer",
) -> FastMCP:
    """Create the agent control MCP server.

    Tools:
    - send_prompt(prompt) - Send a prompt to start an agent run
    - abort_run() - Abort the currently running agent

    Args:
        name: Server name
        container: AgentContainer to control

    Returns:
        FastMCP server instance
    """
    mcp = FastMCP(name)

    @mcp.tool()
    async def send_prompt(prompt: str) -> dict[str, Any]:
        """Send a prompt to start an agent run.

        Args:
            prompt: The prompt text to send to the agent

        Returns:
            Status of the operation
        """
        if container.session is None:
            return {"status": "error", "message": "Agent session not initialized"}

        try:
            await container.session.run(prompt)
            return {"status": "started", "message": "Prompt sent successfully"}
        except Exception as e:
            logger.error(f"Failed to send prompt: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    async def abort_run() -> dict[str, Any]:
        """Abort the currently running agent.

        Returns:
            Status of the operation
        """
        if container.session is None:
            return {"status": "error", "message": "Agent session not initialized"}

        try:
            await container.session.cancel_active_run()
            return {"status": "aborted", "message": "Run aborted successfully"}
        except Exception as e:
            logger.error(f"Failed to abort run: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    return mcp
