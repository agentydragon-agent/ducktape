"""Shared FastMCP helpers for unit tests and demos.

Provides minimal test tools that exercise meaningfully different functionality:

- ``echo(input)`` - Normal tool call: echoes input text back in structured output
- ``raise_reserved()`` - Error handling: raises McpError with reserved policy-denied code
- ``raise_with_gateway_stamp()`` - Gateway testing: raises McpError tagged with policy stamp

Each tool tests a distinct pattern. Removed redundant tools (ping, noop) that
don't add coverage beyond echo().
"""

from __future__ import annotations

from typing import Literal

from fastmcp.server import FastMCP
from mcp import McpError, types as mtypes
from pydantic import BaseModel

from adgn.mcp._shared.constants import POLICY_GATEWAY_STAMP_KEY
from adgn.mcp._shared.fastmcp_flat import mcp_flat_model


class EmptyInput(BaseModel):
    """Empty input for parameterless MCP tools.

    Use when a tool takes no arguments but requires a Pydantic model
    for type safety in the test framework.

    Examples: noop, ping, slow, slow2 tools.
    """


class EchoInput(BaseModel):
    """Input for echo tool."""

    text: str


class EchoOutput(BaseModel):
    """Output for echo tool."""

    echo: str


class SendMessageInput(BaseModel):
    """Input for validation send_message tool.

    Used by validation_server fixture for testing strict validation.
    """

    mime: Literal["text/markdown", "text/plain"]
    content: str


def build_simple_tools(server: FastMCP) -> None:
    """Register the standard simple tools on ``server``.

    The helpers are intentionally deterministic and side-effect free so they can
    be reused across unit, integration, and approval-policy tests.
    """

    @mcp_flat_model(server, name="echo")
    def echo(input: EchoInput) -> EchoOutput:
        return EchoOutput(echo=input.text)

    @mcp_flat_model(server, name="raise_reserved")
    def raise_reserved(input: EmptyInput) -> None:
        raise McpError(mtypes.ErrorData(code=-32950, message="policy_denied"))

    @mcp_flat_model(server, name="raise_with_gateway_stamp")
    def raise_with_gateway_stamp(input: EmptyInput) -> None:
        raise McpError(
            mtypes.ErrorData(
                code=-32000, message="upstream_error", data={POLICY_GATEWAY_STAMP_KEY: True, "note": "spoof"}
            )
        )


def make_simple_mcp(name: str = "simple") -> FastMCP:
    """Create a FastMCP server exposing the shared simple tools."""

    server = FastMCP(name)
    build_simple_tools(server)
    return server


__all__ = ["EchoInput", "EchoOutput", "EmptyInput", "SendMessageInput", "build_simple_tools", "make_simple_mcp"]
