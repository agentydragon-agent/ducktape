"""Shared type aliases for tests."""

from __future__ import annotations

from fastmcp.server import FastMCP
from pydantic import BaseModel

# MCP server specs: either typed specs (BaseModel) or in-process server instances (FastMCP)
# Typed specs are sent over HTTP and rehydrated server-side
# FastMCP instances are mounted directly in-process
McpServerSpecs = dict[str, BaseModel | FastMCP]
