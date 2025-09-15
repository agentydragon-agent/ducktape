from __future__ import annotations


import asyncio
import uuid
from typing import Any, Literal, NewType, Callable as _Callable  # internal alias only

from mcp import types as mcp_types
from .mcp_manager import build_mcp_function

# Types
ApprovalMode = Literal["allow", "ask"]
ToolKind = Literal["tool", "resource_read"]

ToolPolicyFn = _Callable[[dict[str, Any]], ApprovalMode]


# Strongly-typed call identifiers for approvals rendezvous
CallId = NewType("CallId", str)


class ApprovalHub:
    """In-memory approvals rendezvous for pending decisions.

    Usage:
      - await await_decision(call_id, payload) inside the caller; blocks until resolve() is called
      - resolve(call_id, allow=True/False) from UI/driver
    """

    def __init__(self) -> None:
        self._futures: dict[CallId, asyncio.Future[bool]] = {}
        self._lock = asyncio.Lock()

    async def await_decision(self, call_id: CallId, payload: dict[str, Any]) -> bool:
        # The payload is ignored here; caller is responsible for emitting events to UI
        async with self._lock:
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
        return await fut

    def resolve(self, call_id: CallId, allow: bool) -> None:
        fut = self._futures.pop(call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(allow)


def default_allow_all_policy(_: dict[str, Any]) -> ApprovalMode:
    return "allow"


class McpManagerWithApprovals:
    """Opt-in wrapper that gates tool calls via a hardcoded or provided policy.

    Notes:
    - Only call_tool is gated in MVP. read_resource is pass-through for now (see TODO below).
    - The wrapper preserves the underlying manager surface used by the agent: list_tools, list_resources,
      read_resource, call_tool, resolve_function, server_names, get_server_initialize.
    - Approval events are emitted via on_event if provided: approval_pending, approval_decision.
    """

    def __init__(
        self,
        inner: Any,
        hub: ApprovalHub | None = None,
        tool_policy: ToolPolicyFn | None = None,
    ) -> None:
        self._inner = inner
        self._hub = hub or ApprovalHub()
        self._policy = tool_policy or default_allow_all_policy

    # ---- Pass-throughs ----
    async def list_tools(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._inner.list_tools(only=only)

    async def list_resources(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        return await self._inner.list_resources(only=only)

    async def read_resource(self, server: str, uri: str) -> Any:
        # TODO(mpokorny): Consider gating resource reads in a follow-up with kind="resource_read"
        return await self._inner.read_resource(server, uri)

    async def get_server_initialize(self, server: str):
        return await self._inner.get_server_initialize(server)

    @property
    def server_names(self) -> list[str]:
        return list(self._inner.server_names)

    def resolve_function(self, namespaced: str) -> tuple[str, str]:
        from .mcp_manager import parse_mcp_function

        return parse_mcp_function(namespaced)

    # ---- Gated call_tool ----
    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> Any:
        tool_key = build_mcp_function(server, name)
        payload = {
            "kind": "tool",
            "server": server,
            "tool": name,
            "tool_key": tool_key,
            "arguments": arguments or {},
        }
        mode = self._policy(payload)
        if mode == "allow":
            return await self._inner.call_tool(server, name, arguments)

        # ask-mode: block until a decision is provided via ApprovalHub.resolve
        call_id: CallId = CallId(f"appr-{uuid.uuid4().hex}")
        allow = await self._hub.await_decision(call_id, payload)
        if not allow:
            # Synthesize a structured CallToolResult with an error payload the agent will surface
            return mcp_types.CallToolResult(
                content=[],
                isError=True,
                structuredContent={"ok": False, "error": f"User denied: {tool_key}"},
            )
        return await self._inner.call_tool(server, name, arguments)

    # ---- ApprovalHub control (for UI/driver) ----
    @property
    def approval_hub(self) -> ApprovalHub:
        return self._hub

    def resolve_approval(self, call_id: CallId, allow: bool) -> None:
        self._hub.resolve(call_id, allow)
