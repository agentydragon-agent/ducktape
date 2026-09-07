"""Production composition of the reviewed MCP ActionGroups; no dynamic adapter registry."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from pydantic import ValidationError

from x.agentplane.action_service.catalog import ActionCatalog, McpExecutorBinding
from x.agentplane.action_service.mcp_executor import McpActionGroupExecutor
from x.agentplane.action_service.models import Executor


@asynccontextmanager
async def running_executor(catalog: ActionCatalog) -> AsyncIterator[dict[str, Executor]]:
    """Validate all bindings before connecting, then require initial discovery for every group.

    An empty catalog intentionally serves no actions. A configured group must have a valid MCP
    binding and connect/discover successfully; there is no EchoExecutor fallback. Later discovery
    failures retain the adapter's unavailable-and-retry behavior.
    """
    executors: dict[str, McpActionGroupExecutor] = {}
    for key, group in catalog.groups.items():
        if not isinstance(group.executor, McpExecutorBinding):
            raise ValueError(f"ActionGroup {key!r} has an unsupported executor kind; expected 'mcp'")
        try:
            executors[key] = McpActionGroupExecutor.from_group(key, group)
        except ValidationError:
            # Pydantic's default exception text includes raw binding values.
            raise ValueError(f"ActionGroup {key!r} has an invalid MCP binding") from None

    async with AsyncExitStack() as stack:
        for key, executor in executors.items():
            # Register before start: a connected client can fail during initial discovery.
            stack.push_async_callback(executor.close)
            await executor.start()
            if not catalog.groups[key].available:
                raise RuntimeError(f"ActionGroup {key!r} failed initial MCP discovery")
        yield dict(executors)
