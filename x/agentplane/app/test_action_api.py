"""OIDC operator -> BFF -> canonical Action Service -> real MCP, with one durable dispatch."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import cast

import httpx
import pytest
import pytest_bazel
from fastmcp import FastMCP

from util.net import pick_free_port
from util.testing.asgi import serve_app
from util.testing.mock_oidc import build_mock_oidc_app, generate_rsa_keypair
from x.agentplane.action_service import api as service_api
from x.agentplane.action_service.auth import ConfiguredOperatorBearerAuthenticator
from x.agentplane.action_service.catalog import ActionCatalog, ActionGroup, McpExecutorBinding
from x.agentplane.action_service.client import CredentialPlaceholder, OperatorActionServiceClient
from x.agentplane.action_service.database_migrate import apply_migrations
from x.agentplane.action_service.db import ActionStore, make_engine, make_sessionmaker
from x.agentplane.action_service.mcp_executor import McpActionGroupExecutor
from x.agentplane.action_service.models import ActionRequestInput, ActionState, Principal, PrincipalRole
from x.agentplane.action_service.service import ActionService
from x.agentplane.app.api import Provider, create_app
from x.agentplane.app.bridge import RunnerBridge
from x.agentplane.app.conftest import AGENT_AUTH
from x.agentplane.app.decisions import DecisionsClient
from x.agentplane.app.egress import EgressInventory
from x.agentplane.app.identity import TokenReviewer
from x.agentplane.app.inventory import SandboxInventory
from x.agentplane.app.live import LiveIndex
from x.agentplane.app.oidc import OIDCSettings
from x.agentplane.app.trajectory import TrajectoryStore
from x.agentplane.sandbox_auth.http import SandboxPrincipalAuthenticator

CALLER = Principal(issuer="test-workload", subject="test-sandbox", role=PrincipalRole.CALLER)
TEST_BEARER = "test-only-operator-bff"


@dataclass
class Review:
    browser: httpx.AsyncClient
    service: ActionService
    calls: list[str]


@pytest.fixture
async def review(
    db_url: str,
    inventory: SandboxInventory,
    bridge: RunnerBridge,
    store: TrajectoryStore,
    egress: EgressInventory,
    decisions: DecisionsClient,
    live_index: LiveIndex,
    reviewer: TokenReviewer,
    request: pytest.FixtureRequest,
) -> AsyncIterator[Review]:
    apply_migrations(db_url)
    server = FastMCP("test-review")
    calls: list[str] = []

    @server.tool
    def record(message: str) -> dict[str, str]:
        calls.append(message)
        return {"recorded": message}

    group = ActionGroup(
        title="Test review", description="Test-only MCP tool", executor=McpExecutorBinding(description="in-memory MCP")
    )
    catalog = ActionCatalog(groups={"test_review": group})
    async with AsyncExitStack() as stack:
        engine = make_engine(db_url)
        stack.push_async_callback(engine.dispose)
        executor = McpActionGroupExecutor("test_review", group, server)
        stack.push_async_callback(executor.close)
        await executor.start()
        service = ActionService(ActionStore(make_sessionmaker(engine)), catalog, {"test_review": executor})
        stack.push_async_callback(service.close)
        await service.start()
        downstream = service_api.create_app(
            service,
            # This test submits as CALLER directly; it never invokes the workload HTTP surface.
            cast(SandboxPrincipalAuthenticator, None),
            ConfiguredOperatorBearerAuthenticator(
                token_digest=hashlib.sha256(TEST_BEARER.encode()).digest(), subject="test-review-bff"
            ),
            catalog,
        )
        downstream_http = await stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=downstream), base_url="http://test-actions.invalid")
        )
        connection = request.param
        operator_client = (
            None
            if connection == "disabled"
            else OperatorActionServiceClient(
                downstream_http,
                CredentialPlaceholder(value=TEST_BEARER if connection == "configured" else "test-rejected-bearer"),
            )
        )
        private_key, public_key = generate_rsa_keypair()
        idp_port = pick_free_port()
        idp_url, app_url = f"http://127.0.0.1:{idp_port}", "http://test-app.invalid"
        idp = build_mock_oidc_app(
            issuer_url=idp_url,
            private_key=private_key,
            public_key=public_key,
            subject="test-operator-subject",
            extra_id_token_claims={"preferred_username": "test-operator"},
        )
        app = create_app(
            inventory,
            bridge,
            store,
            {provider: ["test-model"] for provider in Provider},
            egress,
            decisions,
            live_index,
            OIDCSettings(
                issuer=idp_url,
                client_id="test-app",
                client_secret="test-only-client-secret",
                session_secret="test-only-session-secret",
                public_base_url=app_url,
            ),
            reviewer,
            operator_actions=operator_client,
        )
        await stack.enter_async_context(serve_app(idp, port=idp_port))
        browser = await stack.enter_async_context(
            httpx.AsyncClient(base_url=app_url, follow_redirects=True, mounts={app_url: httpx.ASGITransport(app=app)})
        )
        yield Review(browser, service, calls)


@pytest.mark.parametrize("review", ["configured"], indirect=True)
async def test_operator_decision_reaches_canonical_service_and_mcp_once(review: Review) -> None:
    browser, service = review.browser, review.service
    pending = await service.submit(
        ActionRequestInput(idempotency_key="test-submit", capability="test_review.record", arguments={"message": "hi"}),
        CALLER,
    )
    path = f"/actions/{pending.id}/decision"
    decision = {"verdict": "allow", "expected_version": pending.version, "idempotency_key": "test-allow"}
    assert (await browser.get("/actions")).status_code == 401
    assert (await browser.get("/actions", headers=AGENT_AUTH)).status_code == 403
    assert (await browser.post(path, headers=AGENT_AUTH, json=decision)).status_code == 403
    assert review.calls == []

    await browser.get("/auth/login")
    assert (await browser.get("/auth/me")).json() == {"username": "test-operator"}
    assert (await browser.get("/actions", params={"state": "succeeded"})).json() == []
    assert [row["id"] for row in (await browser.get("/actions", params={"state": "decision_pending"})).json()] == [
        str(pending.id)
    ]
    assert (
        await browser.post(path, json=decision, headers={"Origin": "https://cross-origin.invalid"})
    ).status_code == 403
    assert (await service.get(pending.id, CALLER)).state is ActionState.DECISION_PENDING
    assert review.calls == []
    allowed = await browser.post(path, json=decision)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["decision"]["issuer"] == "configured-operator:test-review-bff"
    assert (await browser.post(path, json=decision)).status_code == 200
    assert (
        await browser.post(path, json={**decision, "verdict": "deny", "idempotency_key": "late-deny"})
    ).status_code == 409
    async with asyncio.timeout(10):
        while True:
            final = (await browser.get(f"/actions/{pending.id}")).json()
            if final["state"] == "succeeded":
                break
            # Each read awaits service IO; no fixed delay or elapsed-time assertion.
    assert final["execution"]["result"] == {"recorded": "hi"}
    assert review.calls == ["hi"]
    assert [event.state for event in await service.events(pending.id, CALLER)] == [
        ActionState.DECISION_PENDING,
        ActionState.ALLOWED,
        ActionState.DISPATCHING,
        ActionState.RUNNING,
        ActionState.SUCCEEDED,
    ]
    assert (await browser.post(path, json=decision)).json()["execution"]["id"] == final["execution"]["id"]
    assert review.calls == ["hi"]


@pytest.mark.parametrize(("review", "expected"), [("disabled", 503), ("rejected", 401)], indirect=["review"])
async def test_unconfigured_or_rejected_service_auth_fails_closed(review: Review, expected: int) -> None:
    pending = await review.service.submit(
        ActionRequestInput(
            idempotency_key="test-blocked", capability="test_review.record", arguments={"message": "no"}
        ),
        CALLER,
    )
    await review.browser.get("/auth/login")
    assert (await review.browser.get("/actions")).status_code == expected
    assert (
        await review.browser.post(
            f"/actions/{pending.id}/decision",
            json={"verdict": "allow", "expected_version": pending.version, "idempotency_key": "test-blocked-allow"},
        )
    ).status_code == expected
    assert (await review.service.get(pending.id, CALLER)).state is ActionState.DECISION_PENDING
    assert review.calls == []


if __name__ == "__main__":
    pytest_bazel.main()
