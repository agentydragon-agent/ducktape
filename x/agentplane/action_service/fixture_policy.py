"""Opt-in decision provider for the credentialless, no-input MCP staging fixture."""

from pydantic import BaseModel, ConfigDict, Field

from x.agentplane.action_service.catalog import ActionCatalog, Key
from x.agentplane.action_service.models import DecisionContext, PrincipalRole, ProviderOutcome, ProviderVerdict


class FixtureAutoAllow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    group: Key = Field(description="Reviewed group bound only to the credentialless MCP fixture server.")


class FixtureDecisionProvider:
    def __init__(self, config: FixtureAutoAllow, catalog: ActionCatalog, *, sandbox_namespaces: frozenset[str]) -> None:
        group = catalog.groups.get(config.group)
        if group is None or group.executor.kind != "mcp":
            raise ValueError("fixture auto-allow requires a configured MCP ActionGroup")
        self._group = group
        self._capability = f"{config.group}.fixture_info"
        self._sandbox_namespaces = sandbox_namespaces

    @property
    def name(self) -> str:
        return "mcp_fixture"

    async def decide(self, context: DecisionContext) -> ProviderOutcome:
        principal = context.caller_principal
        namespace, separator, sandbox_uid = principal.subject.partition(":")
        if (
            context.capability == self._capability
            and context.arguments == {}
            and principal.role is PrincipalRole.CALLER
            and principal.issuer == "kubernetes-sandbox"
            and namespace in self._sandbox_namespaces
            and separator
            and sandbox_uid
            and ":" not in sandbox_uid
            and self._group.available
            and "fixture_info" in self._group.actions
        ):
            return ProviderOutcome(
                verdict=ProviderVerdict.ALLOW,
                reason_code="credentialless_fixture",
                reason_description="No-input staging fixture Action from an authenticated sandbox.",
            )
        return ProviderOutcome(verdict=ProviderVerdict.NO_OPINION, reason_code="outside_fixture_scope")
