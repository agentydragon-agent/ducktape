"""Shared type aliases for tests."""

from __future__ import annotations

from fastmcp.mcp_config import MCPServerTypes
from fastmcp.server import FastMCP

# MCP server specs: either typed specs (MCPServerTypes) or in-process server instances (FastMCP)
# MCPServerTypes: Pydantic models representing server configs (stdio, http, etc.) - sent over HTTP and rehydrated server-side
# FastMCP: In-process server instances - mounted directly via compositor without serialization
McpServerSpecs = dict[str, MCPServerTypes | FastMCP]
