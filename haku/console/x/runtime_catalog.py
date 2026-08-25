"""Application composition for the runtime implementations linked into Console."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from haku.console.chat_models import RuntimeKind
from haku.console.config import ClaudeRuntimeConfig
from haku.console.x.claude_code.client import cli_over_websocket
from haku.console.x.claude_code.runtime import ClaudeRuntimeAdapter
from haku.console.x.codex_app_server.runtime import CodexRuntimeAdapter
from haku.console.x.runtime import (
    AgentRuntimeResources,
    RuntimeAdapter,
    RuntimeClientFactory,
    RuntimeKey,
    RuntimeRegistry,
)
from haku.console.x.sandbox_claims import SandboxClaims
from haku.console.x.system_prompt import SystemPromptTemplate


def projection_registry() -> RuntimeRegistry:
    """All linked provider interpreters, without execution credentials or sandbox resources."""
    adapters = (ClaudeRuntimeAdapter(), CodexRuntimeAdapter())
    return RuntimeRegistry({adapter.kind: adapter for adapter in adapters})


@dataclass(frozen=True, slots=True)
class RuntimeRegistration:
    """One adapter plus the deploy-owned resources that make it launchable."""

    adapter: RuntimeAdapter
    resources: AgentRuntimeResources

    @property
    def key(self) -> RuntimeKey | RuntimeKind:
        """Resource selector, with a kind-only form for rolling-compatible callers."""
        if self.resources.agent_id is None or self.resources.access_profile_id is None:
            return self.adapter.kind
        return RuntimeKey(self.resources.agent_id, self.adapter.kind)


def execution_registry(*registrations: RuntimeRegistration) -> RuntimeRegistry:
    """Compose every runtime this replica is deliberately configured to execute."""
    adapters = {registration.adapter.kind: registration.adapter for registration in registrations}
    resources = {registration.key: registration.resources for registration in registrations}
    if len(resources) != len(registrations):
        raise ValueError("duplicate configured Agent/runtime resource")
    return RuntimeRegistry(adapters, resources)


def claude_registration(
    config: ClaudeRuntimeConfig,
    claims: SandboxClaims,
    *,
    system_prompt: SystemPromptTemplate,
    client_factory: RuntimeClientFactory = cli_over_websocket,
    agent_id: UUID | None = None,
    access_profile_id: str | None = None,
    execution_environment: Mapping[str, str] | None = None,
) -> RuntimeRegistration:
    """Create the production Haku Claude registration."""
    adapter = ClaudeRuntimeAdapter(client_factory=client_factory)
    return RuntimeRegistration(
        adapter=adapter,
        resources=AgentRuntimeResources(
            claims=claims,
            session_ttl_seconds=config.session_ttl_seconds,
            cwd=config.cwd,
            environment={**config.claude_environment(), **(execution_environment or {})},
            mcp_server_urls={"haku-console": config.mcp_url},
            system_prompt=system_prompt,
            agent_id=agent_id or config.mcp_static_agent_id,
            access_profile_id=access_profile_id,
        ),
    )
