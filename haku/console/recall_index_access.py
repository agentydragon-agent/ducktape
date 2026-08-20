"""Server-side Recall authorization derived from durable Agent access profiles."""

from __future__ import annotations

from typing import Any

from haku.console.mcp_config import AccessProfile
from haku.console.mcp_execution import AgentMcpExecutionCaller, McpExecutionCaller
from haku.console.tool_call_actor import AgentActor, ToolCallActor


class RecallIndexAccessPolicy:
    """Deployment-owned, default-deny logical-index grants selected by Agent profile."""

    def __init__(self, profiles: tuple[AccessProfile, ...]) -> None:
        self._profile_indexes = {profile.id: frozenset(profile.recall_index_ids) for profile in profiles}

    def allowed_indexes(self, caller: ToolCallActor | McpExecutionCaller | None) -> tuple[str, ...]:
        match caller:
            case (
                AgentActor(access_profile_id=access_profile_id)
                | AgentMcpExecutionCaller(access_profile_id=access_profile_id)
            ):
                pass
            case _:
                return ()
        if access_profile_id is None:
            return ()
        return tuple(sorted(self._profile_indexes.get(access_profile_id, ())))

    def allows(self, caller: ToolCallActor | McpExecutionCaller | None, index_id: str) -> bool:
        return index_id in self.allowed_indexes(caller)

    def authorize_index_tool(self, actor: ToolCallActor, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """Reject an unauthorized index request before it reaches the approval queue."""
        if tool_name == "search":
            index_id = arguments.get("index_id")
            return None if isinstance(index_id, str) and self.allows(actor, index_id) else "recall index access denied"
        if tool_name == "index_status":
            return None if self.allowed_indexes(actor) else "recall index access denied"
        return None
