"""Shared contract for resolving an authenticated Haku Agent bearer."""

from typing import Protocol

from haku.console.tool_call_actor import AgentActor


class AgentBearerResolver(Protocol):
    """Resolve a raw Haku bearer to its current Agent authority."""

    async def resolve_agent(self, token: str) -> AgentActor | None: ...
