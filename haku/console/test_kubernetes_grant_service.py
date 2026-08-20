"""Service lifecycle contracts independent of PostgreSQL transport."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_bazel

from haku.console.kubernetes_grant_models import KubernetesGrant, KubernetesGrantStatus, KubernetesRule
from haku.console.kubernetes_grant_service import KubernetesGrantService

_NOW = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
_AGENT = UUID("10000000-0000-4000-8000-000000000001")
_OTHER_AGENT = UUID("10000000-0000-4000-8000-000000000002")


def _rule(verb: str = "get") -> KubernetesRule:
    return KubernetesRule(api_groups=("",), resources=("pods",), verbs=(verb,))


class FakeRepository:
    def __init__(self) -> None:
        self.grants: dict[UUID, KubernetesGrant] = {}
        self.expire_calls: list[tuple[UUID | None, datetime]] = []

    async def create(self, *, agent_id, source_tool_call_id, rules, created_at, expires_at):
        grant = KubernetesGrant(
            grant_id=uuid4(),
            agent_id=agent_id,
            source_tool_call_id=source_tool_call_id,
            rules=tuple(rules),
            status=KubernetesGrantStatus.ACTIVE,
            created_at=created_at,
            expires_at=expires_at,
        )
        self.grants[grant.grant_id] = grant
        return grant

    async def expire(self, *, agent_id=None, now):
        self.expire_calls.append((agent_id, now))
        return 0

    async def list(self, *, agent_id, include_terminal=True):
        return tuple(g for g in self.grants.values() if g.agent_id == agent_id)

    async def get(self, *, agent_id, grant_id):
        grant = self.grants[grant_id]
        assert grant.agent_id == agent_id
        return grant

    async def active_for_agent(self, *, agent_id, now):
        return tuple(
            g for g in self.grants.values() if g.agent_id == agent_id and g.status is KubernetesGrantStatus.ACTIVE
        )

    async def release(self, **kwargs):
        raise AssertionError("not used by this test")

    async def revoke(self, **kwargs):
        raise AssertionError("not used by this test")


@pytest.mark.asyncio
async def test_create_and_match_require_the_explicit_agent_id() -> None:
    repo = FakeRepository()
    service = KubernetesGrantService(repo, max_lifetime=timedelta(hours=1), clock=lambda: _NOW)
    grant = await service.create_grant(
        agent_id=_AGENT, source_tool_call_id="tool-call-1", rules=(_rule(),), expires_at=_NOW + timedelta(minutes=5)
    )

    assert grant.agent_id == _AGENT
    assert (await service.match_request(agent_id=_AGENT, required_rules=(_rule(),))).allowed
    assert not (await service.match_request(agent_id=_OTHER_AGENT, required_rules=(_rule(),))).allowed
    assert repo.expire_calls[-1][0] == _OTHER_AGENT


@pytest.mark.asyncio
async def test_match_returns_the_earliest_expiration_bound() -> None:
    repo = FakeRepository()
    service = KubernetesGrantService(repo, max_lifetime=timedelta(hours=1), clock=lambda: _NOW)
    first = await service.create_grant(
        agent_id=_AGENT, source_tool_call_id="tool-call-1", rules=(_rule(),), expires_at=_NOW + timedelta(minutes=10)
    )
    second = await service.create_grant(
        agent_id=_AGENT, source_tool_call_id="tool-call-2", rules=(_rule(),), expires_at=_NOW + timedelta(minutes=2)
    )

    decision = await service.match_request(agent_id=_AGENT, required_rules=(_rule(),))

    assert decision.allowed
    assert decision.grant_id == second.grant_id
    assert decision.expires_at == second.expires_at
    assert decision.grant_id != first.grant_id


if __name__ == "__main__":
    pytest_bazel.main()
