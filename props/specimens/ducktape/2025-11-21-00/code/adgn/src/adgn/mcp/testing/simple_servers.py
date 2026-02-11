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

from fastmcp.server import FastMCP
from mcp import McpError, types as mtypes

from adgn.mcp._shared.constants import POLICY_GATEWAY_STAMP_KEY


def build_simple_tools(server: FastMCP) -> None:
    """Register the standard simple tools on ``server``.

    The helpers are intentionally deterministic and side-effect free so they can
    be reused across unit, integration, and approval-policy tests.
    """

    @server.tool(name="echo")
    def echo(text: str) -> dict[str, str]:
        return {"echo": text}

    @server.tool(name="ping")
    def ping() -> str:
        return "pong"

    @server.tool(name="noop")
    def noop() -> dict[str, bool]:
        return {"ok": True}

    @server.tool(name="raise_reserved")
    def raise_reserved() -> None:
        raise McpError(mtypes.ErrorData(code=-32950, message="policy_denied"))

    @server.tool(name="raise_with_gateway_stamp")
    def raise_with_gateway_stamp() -> None:
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


__all__ = ["build_simple_tools", "make_simple_mcp"]
