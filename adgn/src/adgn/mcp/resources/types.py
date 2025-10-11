from __future__ import annotations

from mcp import types as mcp_types
from pydantic import BaseModel, Field


class ResourceEntry(BaseModel):
    server: str = Field(description="Origin MCP server name")
    resource: mcp_types.Resource
