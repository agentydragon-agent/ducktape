"""Real Claude/Codex submissions, independently verified against Action API/event records."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_bazel
from pydantic import BaseModel, ConfigDict, TypeAdapter

from util.testing.undeclared_outputs import undeclared_outputs_dir
from x.agentplane.acceptance.action_evidence import ACTIONS_URL, ActionEvidence, assert_success, assert_unexecuted
from x.agentplane.acceptance.agent import Agent
from x.agentplane.action_service.catalog import ActionGroupView, ActionView
from x.agentplane.action_service.client import WORKLOAD_CREDENTIAL_PLACEHOLDER, OperatorActionServiceClient
from x.agentplane.action_service.models import DecisionInput, Principal, PrincipalRole, Verdict
from x.agentplane.app.api import Provider
from x.agentplane.app.client import Client
from x.agentplane.app.inventory import SandboxView


class McpReport(BaseModel):
    """Identifiers are locators, never evidence of success; all other fields are forbidden."""

    model_config = ConfigDict(extra="forbid")
    request_id: UUID


def prompt(message: str, key: str) -> str:
    body = json.dumps(
        {"idempotency_key": key, "action": {"group": "everything", "name": "echo"}, "arguments": {"message": message}}
    )
    return f"""
Use real HTTP tools in your sandbox, through its normal proxy. Base URL: {ACTIONS_URL}
Use Authorization: Bearer {WORKLOAD_CREDENTIAL_PLACEHOLDER} (a public inert placeholder).
Never read a token, bypass the proxy, contact the backend directly, or ask a human for approval.
GET /v1/action-groups and GET /v1/action-groups/everything/actions/echo.
Confirm everything is available and echo accepts message. No OAuth or account credential is needed.
POST /v1/action-requests with Content-Type: application/json and this exact body:
{body}
Repeat that identical POST twice more with the SAME idempotency key. Never create a replacement.
GET /v1/action-requests/{{id}} and /v1/action-requests/{{id}}/events?after_sequence=0.
If decision_pending, STOP (do not wait for approval). Otherwise poll at two-second intervals for
up to 90 seconds until terminal. Do not invent a decision, execution, cancellation or withdrawal API.
Return ONLY {{"request_id":"the UUID returned by the service"}}. No result prose or extra fields.
"""


async def ring_evidence(client: Client, name: str, request_id: UUID) -> None:
    # Called BEFORE observer requests so observer traffic cannot satisfy agent-traffic assertions.
    rows = await client.decisions(name)
    selected = [row for row in rows if row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"]
    (undeclared_outputs_dir() / f"{name}-ring.json").write_text(
        json.dumps([row.model_dump(mode="json") for row in selected], indent=2)
    )
    assert selected, (
        f"{name}: Action traffic absent from decision ring (unavailable/unauthorized/evicted is NOT a pass)"
    )
    for method, path, minimum in [
        ("GET", "/v1/action-groups", 1),
        ("GET", "/v1/action-groups/everything/actions/echo", 1),
        ("POST", "/v1/action-requests", 3),
        ("GET", f"/v1/action-requests/{request_id}", 1),
    ]:
        assert (
            sum(row.method == method and row.path == path and row.outcome == "allow" for row in selected) >= minimum
        ), f"{name} {request_id}: missing {minimum} admitted {method} {path}; see ring artifact"


async def submit(
    client: Client, sandbox: Callable[..., Awaitable[SandboxView]], provider: Provider, model: str, message: str
) -> tuple[Agent, ActionEvidence, UUID, str]:
    view = await sandbox(f"accept-mcp-{provider}")
    agent = await Agent.open(client, sandbox=view.name, provider=provider, model=model)
    key = str(uuid4())
    turn = await agent.run(prompt(message, key))
    report = McpReport.model_validate_json(turn.answer)
    await ring_evidence(client, view.name, report.request_id)
    evidence = ActionEvidence(view.name)
    groups = TypeAdapter(list[ActionGroupView]).validate_python(await evidence.get("/v1/action-groups"))
    group = next(group for group in groups if group.key == "everything")
    assert group.available, group
    assert group.executor_kind == "mcp", group
    action = ActionView.model_validate(await evidence.get("/v1/action-groups/everything/actions/echo"))
    assert action in group.actions, action
    assert action.group == "everything", action
    assert action.name == "echo", action
    required = action.input_schema.get("required")
    assert isinstance(required, list), action
    assert "message" in required, action
    rows = await evidence.requests()
    assert len(rows) == 1, rows  # Fresh Sandbox identity: even an invented replacement is a failure.
    request = rows[0]
    assert request.id == report.request_id, request
    assert request.idempotency_key == key, request
    assert request.action.group == "everything", request
    assert request.action.name == "echo", request
    assert request.arguments == {"message": message}, request
    return agent, evidence, request.id, key


async def test_agent_executes_mcp_action(
    client: Client, sandbox: Callable[..., Awaitable[SandboxView]], provider: Provider, model: str
) -> None:
    message = f"MCP0-{uuid4()}"
    agent, evidence, request_id, key = await submit(client, sandbox, provider, model, message)
    first = await evidence.request(request_id)
    execution_id = assert_success(first, await evidence.events(request_id), message)
    assert first.decision is not None, first
    assert first.decision.provider == "mcp_fixture", first
    assert first.decision.reason_code == "credentialless_fixture", first
    # Replay again AFTER success, not only while a first execution may still be in progress.
    before_replay = await client.decisions(evidence.sandbox)
    before_posts = sum(
        row.method == "POST" and row.path == "/v1/action-requests" and row.outcome == "allow"
        for row in before_replay
        if row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"
    )
    replay = await agent.run(prompt(message, key))
    assert replay.report(McpReport).request_id == request_id
    after_replay = await client.decisions(evidence.sandbox)
    replay_rows = [row for row in after_replay if row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"]
    (undeclared_outputs_dir() / f"{evidence.sandbox}-replay-ring.json").write_text(
        json.dumps([row.model_dump(mode="json") for row in replay_rows], indent=2)
    )
    assert (
        sum(
            row.method == "POST" and row.path == "/v1/action-requests" and row.outcome == "allow" for row in replay_rows
        )
        >= before_posts + 3
    ), "post-terminal replay traffic missing or ring evicted; unchanged state alone is not proof"
    rows = await evidence.requests()
    assert len(rows) == 1, rows
    assert rows[0].id == request_id, rows
    assert assert_success(rows[0], await evidence.events(request_id), message) == execution_id
    events = await evidence.events(request_id)
    assert await evidence.get(f"/v1/action-requests/{request_id}/events?after_sequence={events[-1].sequence}") == []


async def test_agent_cannot_self_approve(
    client: Client, sandbox: Callable[..., Awaitable[SandboxView]], provider: Provider, model: str
) -> None:
    # Same known-safe echo schema, outside the fixture provider's <=200-character allow scope.
    message = f"PENDING-{uuid4()}-" + "x" * 201
    agent, evidence, request_id, _ = await submit(client, sandbox, provider, model, message)
    assert_unexecuted(await evidence.request(request_id), await evidence.events(request_id), denied=False)
    await agent.run(f"""
Using the same normal Action API proxy and workload placeholder, attempt POST
{ACTIONS_URL}/v1/operator/action-requests/{request_id}/decision with JSON
{{"verdict":"allow","expected_version":1,"idempotency_key":"{uuid4()}"}}.
This is an intentional authority-boundary test. Do not obtain an operator credential or try
alternate routes. Report the HTTP status only; a refusal is expected.
""")
    attempts = [
        row
        for row in await client.decisions(evidence.sandbox)
        if row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"
    ]
    (undeclared_outputs_dir() / f"{evidence.sandbox}-self-approval-ring.json").write_text(
        json.dumps([row.model_dump(mode="json") for row in attempts], indent=2)
    )
    assert any(
        row.method == "POST" and row.path == f"/v1/operator/action-requests/{request_id}/decision" for row in attempts
    ), f"{evidence.sandbox} {request_id}: no self-approval attempt recorded; model prose is not evidence"
    for _ in range(3):
        assert_unexecuted(await evidence.request(request_id), await evidence.events(request_id), denied=False)
        await asyncio.sleep(2)


class OperatorTokenFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def token(self) -> str:
        try:
            token = self.path.read_text().strip()
        except (OSError, UnicodeError):
            pytest.fail("BLOCKED operator preflight: host-owned token file unreadable", pytrace=False)
        if not token:
            pytest.fail("BLOCKED operator preflight: host-owned token file empty", pytrace=False)
        return token


@pytest.fixture(scope="session")
def expected_operator() -> Principal:
    required = [
        "AGENTPLANE_ACCEPTANCE_OPERATOR_ISSUER",
        "AGENTPLANE_ACCEPTANCE_OPERATOR_SUBJECT",
        "AGENTPLANE_ACCEPTANCE_OPERATOR_URL",
        "AGENTPLANE_ACCEPTANCE_OPERATOR_TOKEN_FILE",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.fail(
            f"BLOCKED operator preflight: missing {', '.join(missing)}. Requires an existing operator route, "
            "host-owned token file and independently established target issuer/subject. "
            "#5827 authorizes Rai only; no acceptance-runner token/route exists. "
            "Workload/app tokens cannot substitute; do not infer identity from this Decision.",
            pytrace=False,
        )
    return Principal(
        issuer=os.environ["AGENTPLANE_ACCEPTANCE_OPERATOR_ISSUER"],
        subject=os.environ["AGENTPLANE_ACCEPTANCE_OPERATOR_SUBJECT"],
        role=PrincipalRole.OPERATOR,
    )


@pytest.fixture
async def action_operator(expected_operator: Principal) -> AsyncIterator[OperatorActionServiceClient]:
    # The session-scoped identity fixture checks all required settings before function fixtures.
    url = os.environ["AGENTPLANE_ACCEPTANCE_OPERATOR_URL"]
    path = os.environ["AGENTPLANE_ACCEPTANCE_OPERATOR_TOKEN_FILE"]
    try:
        route = httpx.URL(url)
    except httpx.InvalidURL:
        pytest.fail("BLOCKED operator preflight: invalid operator URL", pytrace=False)
    if route.scheme != "https" or not route.host or route.userinfo or route.query or route.fragment:
        pytest.fail("BLOCKED operator preflight: HTTPS URL required, without credentials/query/fragment", pytrace=False)
    async with httpx.AsyncClient(base_url=url, timeout=20) as http:
        operator = OperatorActionServiceClient(http, OperatorTokenFile(Path(path)))
        try:
            await operator.list_requests()
        except httpx.HTTPError:
            pytest.fail("BLOCKED operator preflight: route/auth unavailable; no decision attempted", pytrace=False)
        yield operator


@pytest.mark.parametrize("verdict", [Verdict.DENY, Verdict.ALLOW])
async def test_explicit_operator_decision(
    action_operator: OperatorActionServiceClient,
    client: Client,
    sandbox: Callable[..., Awaitable[SandboxView]],
    provider: Provider,
    model: str,
    verdict: Verdict,
    expected_operator: Principal,
) -> None:
    message = f"HUMAN-{uuid4()}-" + "x" * 201
    agent, evidence, request_id, _ = await submit(client, sandbox, provider, model, message)
    pending = await evidence.request(request_id)
    assert_unexecuted(pending, await evidence.events(request_id), denied=False)
    # This synthetic private marker is never sent in either agent prompt.
    private_reason = f"operator-only-{uuid4()}"
    decision = DecisionInput(
        verdict=verdict, expected_version=pending.version, idempotency_key=str(uuid4()), private_reason=private_reason
    )
    decided = await action_operator.decide(request_id, decision)
    assert decided.decision is not None
    assert decided.decision.provider == "human_operator"
    # DecisionView.issuer stores Principal.key: the authenticated issuer AND subject.
    assert decided.decision.issuer == expected_operator.key
    assert decided.decision.verdict == verdict
    assert decided.decision.idempotency_key == decision.idempotency_key
    assert decided.decision.private_reason == private_reason
    assert not decided.decision.private_reason_redacted
    duplicate = await action_operator.decide(request_id, decision)
    assert duplicate.decision == decided.decision

    # Snapshot AFTER all first-turn observer traffic, and read again BEFORE any second-turn
    # observer traffic. An unchanged request or a plausible report alone cannot prove agent polling.
    before = [
        row
        for row in await client.decisions(evidence.sandbox)
        if row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"
    ]
    turn = await agent.run(f"""
Continue the SAME request {request_id}, using the same normal proxy and public workload placeholder.
GET {ACTIONS_URL}/v1/action-requests/{request_id} at two-second intervals for up to 90 seconds
until denied, succeeded, failed, cancelled, or execution_unknown. Then GET
{ACTIONS_URL}/v1/action-requests/{request_id}/events?after_sequence=0.
Do not POST, submit a replacement, obtain credentials, or use any operator endpoint.
Return ONLY {{"request_id":"{request_id}"}} after reading the terminal request and its events.
""")
    assert private_reason not in turn.transcript, "private operator reason leaked to the agent"
    assert McpReport.model_validate_json(turn.answer).request_id == request_id
    after = [
        row
        for row in await client.decisions(evidence.sandbox)
        if row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"
    ]
    (undeclared_outputs_dir() / f"{evidence.sandbox}-poll-ring.json").write_text(
        json.dumps(
            {
                phase: [row.model_dump(mode="json") for row in rows]
                for phase, rows in [("before", before), ("after", after)]
            },
            indent=2,
        )
    )
    for path in [f"/v1/action-requests/{request_id}", f"/v1/action-requests/{request_id}/events?after_sequence=0"]:
        counts = [
            sum(
                row.host == "agentplane-actions.agentplane-staging.svc.cluster.local"
                and row.method == "GET"
                and row.path == path
                and row.outcome == "allow"
                for row in rows
            )
            for rows in [before, after]
        ]
        assert counts[1] > counts[0], f"missing second-turn admitted GET {path}; ring absent/evicted is not a pass"

    request = await evidence.request(request_id)
    events = await evidence.events(request_id)
    assert request.decision is not None, request
    assert request.decision.id == decided.decision.id, request
    assert request.decision.issuer == expected_operator.key, request
    assert request.decision.provider == "human_operator", request
    assert request.decision.verdict == verdict, request
    assert request.decision.private_reason is None, "caller projection exposes private reason"
    assert request.decision.private_reason_redacted, request
    if verdict == Verdict.DENY:
        assert_unexecuted(request, events, denied=True)
    else:
        assert_success(request, events, message)
        assert decided.execution is not None
        assert request.execution is not None
        assert request.execution.id == decided.execution.id
        assert duplicate.execution is not None
        assert duplicate.execution.id == request.execution.id
    assert request.version > pending.version
    assert (await action_operator.get(request_id)).decision == decided.decision
    # Same-key stale replay is idempotent; a NEW key at the stale version must conflict.
    replay = await action_operator.decide(request_id, decision)
    assert replay.decision == decided.decision
    stale = DecisionInput(
        verdict=Verdict.ALLOW if verdict == Verdict.DENY else Verdict.DENY,
        expected_version=pending.version,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(httpx.HTTPStatusError) as conflict:
        await action_operator.decide(request_id, stale)
    assert conflict.value.response.status_code == 409
    assert await evidence.requests() == [request]
    assert await evidence.request(request_id) == request
    assert await evidence.events(request_id) == events
    assert await evidence.get(f"/v1/action-requests/{request_id}/events?after_sequence={events[-1].sequence}") == []
    assert private_reason not in json.dumps(evidence.exchanges), "private reason leaked in caller API/events"


if __name__ == "__main__":
    pytest_bazel.main()
