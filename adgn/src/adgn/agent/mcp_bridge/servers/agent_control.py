"""Agent control MCP server.

Provides tools for controlling agent execution:
- send_prompt: Send a prompt to start an agent run
- abort_run: Abort the currently running agent

This server is only mounted for internal agents (not external).
External agents are controlled by their own environment.

DEPRECATED: Use AgentContainer.make_control_server() instead.
This module is kept for backwards compatibility with existing tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from adgn.agent.runtime.container import AgentContainer


def make_agent_control_server(name: str, container: AgentContainer) -> FastMCP:
    """Create the agent control MCP server.

    DEPRECATED: Use container.make_control_server(name) instead.

    Args:
        name: Server name
        container: AgentContainer to control

    Returns:
        FastMCP server instance
    """
    return container.make_control_server(name)
