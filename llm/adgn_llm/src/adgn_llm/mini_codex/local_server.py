from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from typing import Any

ToolDef = tuple[str, Mapping[str, Any], Callable[[dict[str, Any]], Any]]

class LocalServer(ABC):
    """Abstract base for in-process MCP-like servers.

    Implement get_tools() to expose tool name -> (description, parameters_schema, handler).
    Handlers can capture state from 'self'.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get_tools(self) -> dict[str, ToolDef]:
        raise NotImplementedError

    async def close(self) -> None:
        return None
