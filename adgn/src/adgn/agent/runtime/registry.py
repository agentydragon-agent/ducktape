from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from adgn.agent.persist import Persistence
from adgn.agent.runtime.spec_utils import rehydrate_mcp_specs
from adgn.agent.runtime.specs import McpServerSpec
from adgn.openai_utils.model import OpenAIModelProto

from .container import AgentContainer, build_container


@dataclass
class AgentRegistry:
    persistence: Persistence
    model: str
    client_factory: Callable[[str], OpenAIModelProto] | None = None
    _items: dict[str, AgentContainer] = field(default_factory=dict)

    def get(self, agent_id: str) -> AgentContainer | None:
        return self._items.get(agent_id)

    def list(self) -> list[AgentContainer]:
        return list(self._items.values())

    async def create(
        self,
        agent_id: str,
        specs: dict[str, McpServerSpec],
        *,
        with_ui: bool = True,
        system: str | None = None,
    ) -> AgentContainer:
        c = await build_container(
            agent_id=agent_id,
            specs=specs,
            persistence=self.persistence,
            model=self.model,
            client_factory=self.client_factory,
            with_ui=with_ui,
            system=system,
        )
        self._items[agent_id] = c
        return c

    async def ensure_live(self, agent_id: str, *, with_ui: bool = True) -> AgentContainer:
        """Return a live container for agent_id, starting it from persisted specs if needed.

        Raises KeyError if the agent does not exist in persistence. Propagates
        validation errors for invalid specs and container startup errors.
        """
        c = self.get(agent_id)
        if c is not None:
            return c
        row = await self.persistence.get_agent(agent_id)
        if row is None:
            raise KeyError(f"agent not found: {agent_id}")
        specs = rehydrate_mcp_specs(row.specs)
        await self.create(agent_id, specs, with_ui=with_ui)
        assert self.get(agent_id) is not None
        return self.get(agent_id)  # type: ignore[return-value]

    def remove(self, agent_id: str) -> None:
        self._items.pop(agent_id, None)

    async def close_all(self) -> None:
        items = list(self._items.values())
        for c in items:
            await c.close()
        self._items.clear()
