"""Legacy container module - minimal compatibility shims.

This module contains only the pieces still needed for backward compatibility:
- UiFacet: UI manager + bus wrapper
- default_client_factory: Default LLM client factory

The old AgentContainer has been replaced by the new architecture:
- MCPInfrastructure (core MCP + policy gateway)
- LocalAgentRuntime (MiniCodex agent)
- AgentRuntime (wrapper combining both)

See:
- runtime/infrastructure.py for infrastructure setup
- runtime/local_runtime.py for agent runtime
- runtime/registry.py for AgentRuntime and AgentRegistry
"""

from __future__ import annotations

from dataclasses import dataclass

from adgn.agent.server.bus import ServerBus
from adgn.agent.server.runtime import ConnectionManager
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto


def default_client_factory(model: str) -> OpenAIModelProto:
    """Default LLM client factory used when no custom factory is provided."""
    return build_client(model, enable_debug_logging=True)


@dataclass
class UiFacet:
    manager: ConnectionManager
    ui_bus: ServerBus
