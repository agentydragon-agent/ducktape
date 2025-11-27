"""MCP Bridge module for Phase 5 two-compositor architecture.

This module provides:
- Token-based routing to different MCP compositors
- Infrastructure registry for agent lifecycle management
- MCP servers for agent management and control
- Global compositor factory
"""

from adgn.agent.mcp_bridge.auth import TokenRoutingASGI, load_tokens
from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor
from adgn.agent.mcp_bridge.registry import InfrastructureRegistry

__all__ = [
    "InfrastructureRegistry",
    "TokenRoutingASGI",
    "create_global_compositor",
    "load_tokens",
]
