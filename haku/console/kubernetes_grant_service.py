"""Application service for explicit-Agent Kubernetes grants and conservative rule matching."""

from __future__ import annotations

import datetime
from collections.abc import Collection, Sequence
from typing import Any, Protocol
from uuid import UUID

from haku.console.kubernetes_grant_models import (
    KubernetesGrant,
    KubernetesGrantCreate,
    KubernetesGrantDecision,
    KubernetesRule,
)


class KubernetesGrantRepository(Protocol):
    async def create(
        self,
        *,
        agent_id: UUID,
        source_tool_call_id: str,
        rules: Sequence[KubernetesRule],
        created_at: datetime.datetime,
        expires_at: datetime.datetime,
    ) -> KubernetesGrant: ...

    async def list(self, *, agent_id: UUID, include_terminal: bool = True) -> tuple[KubernetesGrant, ...]: ...

    async def get(self, *, agent_id: UUID, grant_id: UUID) -> KubernetesGrant: ...

    async def release(self, *, agent_id: UUID, grant_id: UUID, reason: str) -> KubernetesGrant: ...

    async def revoke(self, *, agent_id: UUID, grant_id: UUID, reason: str) -> KubernetesGrant: ...

    async def expire(self, *, now: datetime.datetime, agent_id: UUID | None = None) -> int: ...

    async def active_for_agent(self, *, agent_id: UUID, now: datetime.datetime) -> tuple[KubernetesGrant, ...]: ...


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _wildcard_covers(granted: Collection[str], requested: Collection[str]) -> bool:
    """Whether a grant's values cover all values in the request.

    ``*`` is the only wildcard accepted here.  Empty requested values are treated as the
    canonical empty Kubernetes value (for example, the core API group), not as "all".
    """

    if "*" in granted:
        return True
    return set(requested).issubset(granted)


def _resource_names_cover(granted: Collection[str], requested: Collection[str]) -> bool:
    # Kubernetes RBAC's empty resourceNames means all names. A named request cannot be covered by
    # a grant listing only a different subset. Conversely, a list/watch request has no finite name
    # set and therefore requires an all-names grant.
    if not requested:
        return not granted
    return not granted or set(requested).issubset(granted)


def _non_resource_url_covers(granted: str, requested: str) -> bool:
    if granted in {"*", requested}:
        return True
    # Kubernetes supports a trailing wildcard for a URL path. Do not normalize paths or accept
    # arbitrary glob syntax: exact path and a single terminal /* are deliberately conservative.
    return granted.endswith("/*") and requested.startswith(granted[:-1])


def rule_covers(granted: KubernetesRule, requested: KubernetesRule) -> bool:
    """Return true only when one grant rule covers the entire required rule."""

    granted_is_non_resource = bool(granted.non_resource_urls)
    requested_is_non_resource = bool(requested.non_resource_urls)
    if granted_is_non_resource != requested_is_non_resource:
        return False
    if not _wildcard_covers(granted.verbs, requested.verbs):
        return False
    if requested_is_non_resource:
        return all(
            any(_non_resource_url_covers(granted_url, requested_url) for granted_url in granted.non_resource_urls)
            for requested_url in requested.non_resource_urls
        )
    return (
        _wildcard_covers(granted.api_groups, requested.api_groups)
        and _wildcard_covers(granted.resources, requested.resources)
        and _resource_names_cover(granted.resource_names, requested.resource_names)
    )


def rules_cover(granted: Sequence[KubernetesRule], required: Sequence[KubernetesRule]) -> bool:
    """Every required rule must be covered by one grant rule; no partial matches are accepted."""

    return bool(required) and all(any(rule_covers(candidate, needed) for candidate in granted) for needed in required)


class KubernetesGrantService:
    """Own grant lifecycle and matching for one explicit Agent identity.

    No method reads a ContextVar, ambient request, global caller, or tool arguments to determine
    ownership. The caller must provide ``agent_id`` on every operation that is Agent-scoped.
    """

    def __init__(
        self, repository: KubernetesGrantRepository, *, max_lifetime: datetime.timedelta, clock: Any = _utcnow
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._max_lifetime = max_lifetime
        if max_lifetime <= datetime.timedelta():
            raise ValueError("max_lifetime must be positive")

    async def create_grant(
        self,
        *,
        agent_id: UUID,
        source_tool_call_id: str,
        rules: Sequence[KubernetesRule],
        expires_at: datetime.datetime,
    ) -> KubernetesGrant:
        """Create a grant for exactly ``agent_id`` and retain source-call provenance."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("grant service clock must return a timezone-aware datetime")
        create = KubernetesGrantCreate(
            agent_id=agent_id, source_tool_call_id=source_tool_call_id, rules=tuple(rules), expires_at=expires_at
        )
        if create.expires_at <= now:
            raise ValueError("expires_at must be in the future")
        if create.expires_at > now + self._max_lifetime:
            raise ValueError("expires_at exceeds the configured grant lifetime")
        return await self._repository.create(
            agent_id=create.agent_id,
            source_tool_call_id=create.source_tool_call_id,
            rules=create.rules,
            created_at=now,
            expires_at=create.expires_at,
        )

    async def list_grants(self, *, agent_id: UUID, include_terminal: bool = True) -> tuple[KubernetesGrant, ...]:
        await self.expire_grants(agent_id=agent_id)
        return await self._repository.list(agent_id=agent_id, include_terminal=include_terminal)

    async def get_grant(self, *, agent_id: UUID, grant_id: UUID) -> KubernetesGrant:
        grant = await self._repository.get(agent_id=agent_id, grant_id=grant_id)
        if grant.status.value == "active" and grant.expires_at <= self._clock():
            await self._repository.expire(agent_id=agent_id, now=self._clock())
            grant = await self._repository.get(agent_id=agent_id, grant_id=grant_id)
        return grant

    async def release_grant(self, *, agent_id: UUID, grant_id: UUID, reason: str = "released") -> KubernetesGrant:
        return await self._repository.release(agent_id=agent_id, grant_id=grant_id, reason=reason)

    async def revoke_grant(self, *, agent_id: UUID, grant_id: UUID, reason: str) -> KubernetesGrant:
        return await self._repository.revoke(agent_id=agent_id, grant_id=grant_id, reason=reason)

    async def expire_grants(self, *, agent_id: UUID | None = None) -> int:
        return await self._repository.expire(agent_id=agent_id, now=self._clock())

    async def match_request(
        self, *, agent_id: UUID, required_rules: Sequence[KubernetesRule]
    ) -> KubernetesGrantDecision:
        """Match one request against active grants and return the earliest expiry bound."""

        now = self._clock()
        required = tuple(required_rules)
        if not required:
            raise ValueError("required_rules must not be empty")
        await self._repository.expire(agent_id=agent_id, now=now)
        matching = [
            grant
            for grant in await self._repository.active_for_agent(agent_id=agent_id, now=now)
            if rules_cover(grant.rules, required)
        ]
        if matching:
            grant = min(matching, key=lambda item: item.expires_at)
            return KubernetesGrantDecision(
                allowed=True,
                grant_id=grant.grant_id,
                expires_at=grant.expires_at,
                reason="active Kubernetes grant covers the request",
            )
        return KubernetesGrantDecision(allowed=False, reason="no active Kubernetes grant covers the request")
