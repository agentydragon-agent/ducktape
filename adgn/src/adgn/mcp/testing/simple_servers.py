"""Shared FastMCP helpers for unit tests and demos.

These utilities provide a lightweight FastMCP server that exposes a handful of
simple tools used across the test suite:

- ``echo(text)`` returns structured content ``{"echo": text}``
- ``ping()`` returns ``"pong"`` for quick reachability checks
- ``noop()`` returns ``{"ok": True}`` as a placeholder action
- ``raise_reserved()`` raises ``McpError`` with the reserved policy-denied code
- ``raise_with_gateway_stamp()`` raises ``McpError`` tagged with the policy
  gateway stamp to exercise gateway pass-through logic.

Tests previously duplicated these helpers (and imported ``adgn.mcp.echo``).
Centralising them here keeps behaviour consistent and avoids redundant fixtures.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.server import FastMCP
from mcp import McpError, types as mtypes
from pydantic import BaseModel

from adgn.mcp._shared.constants import POLICY_GATEWAY_STAMP_KEY
from adgn.mcp._shared.fastmcp_flat import mcp_flat_model


class EchoInput(BaseModel):
    """Input for echo tool.

    Simple tool that echoes back the provided text.
    """

    text: str


class SendMessageInput(BaseModel):
    """Input for send_message validation tool.

    Strictly requires text/markdown mime type for validation testing.
    """

    mime: Literal["text/markdown"]
    content: str


class EmptyInput(BaseModel):
    """Empty input for parameterless MCP tools.

    Use when a tool takes no arguments but requires a Pydantic model
    for type safety in the test framework.

    Examples: noop, ping, slow, slow2 tools.
    """


def build_simple_tools(server: FastMCP) -> None:
    """Register the standard simple tools on ``server``.

    The helpers are intentionally deterministic and side-effect free so they can
    be reused across unit, integration, and approval-policy tests.
    """

    @mcp_flat_model(server, name="echo")
    def echo(input: EchoInput) -> dict[str, str]:
        return {"echo": input.text}

    @mcp_flat_model(server, name="ping")
    def ping(input: EmptyInput) -> str:
        return "pong"

    @mcp_flat_model(server, name="noop")
    def noop(input: EmptyInput) -> dict[str, bool]:
        return {"ok": True}

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


__all__ = ["EchoInput", "EmptyInput", "SendMessageInput", "build_simple_tools", "make_simple_mcp"]
