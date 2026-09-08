"""Real staging agents discover, submit, poll and report an MCP-backed Action."""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from http import HTTPStatus
from typing import Literal
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_bazel
from pydantic import BaseModel, ConfigDict, JsonValue, SecretStr

from x.agentplane.acceptance.agent import Agent
from x.agentplane.action_service.client import WORKLOAD_CREDENTIAL_PLACEHOLDER
from x.agentplane.action_service.models import ActionRequestView, ActionState, DecisionInput, ExecutionState, Verdict
from x.agentplane.app.api import Provider
from x.agentplane.app.client import Client
from x.agentplane.app.inventory import SandboxView
from x.agentplane.app.oidc import SECURE_COOKIE


class McpReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    state: Literal["succeeded"]
    output: dict[str, JsonValue]


async def test_agent_executes_mcp_action(
    client: Client, sandbox: Callable[..., Awaitable[SandboxView]], provider: Provider, model: str
) -> None:
    view = await sandbox(f"accept-mcp-{provider}")
    agent = await Agent.open(client, sandbox=view.name, provider=provider, model=model)
    marker = f"MCP0-{uuid4()}"
    idempotency_key = str(uuid4())
    turn = await agent.run(f"""
Test the real Agentplane Actions HTTP API from your sandbox using HTTP tools or a shell.
Base URL: http://agentplane-actions.agentplane-staging.svc.cluster.local:8080
For these HTTP requests use the public placeholder Authorization: Bearer {WORKLOAD_CREDENTIAL_PLACEHOLDER}.
The sandbox's normal proxy supplies your workload identity. Do not bypass the proxy,
read a real token, connect to the MCP server directly, or ask a human for approval.

GET /v1/action-groups, then GET /v1/action-groups/everything/actions/echo.
Check that the everything group is available and offers echo with a message argument.
POST /v1/action-requests with Content-Type: application/json and this body:
{{"idempotency_key": "{idempotency_key}", "action": {{"group": "everything", "name": "echo"}}, "arguments": {{"message": "{marker}"}}}}
Use the returned request ID to poll GET /v1/action-requests/{{id}}/events?after_sequence=0
and GET /v1/action-requests/{{id}} until terminal. Advance the event cursor to the last
sequence you received; wait briefly between polls. Do not create a replacement request
or change the idempotency key. Stop and report a failure if the state becomes denied,
failed, cancelled, or execution_unknown, or polling makes no progress for 90 seconds.

Return only JSON with request_id, state, and output copied from the terminal request's
execution.result. Do the HTTP calls; do not infer or fabricate a result from this prompt.
""")
    report = turn.report(McpReport)
    assert report.output == {"content": [f"Echo: {marker}"]}, turn.transcript


@pytest.fixture
async def operator_bff(base_url: str) -> AsyncIterator[httpx.AsyncClient]:
    """A runner-provided real OIDC session, never a locally signed cookie or inserted DB row."""
    for name in ("SESSION_COOKIE", "USERNAME", "ISSUER", "SUBJECT"):
        if not os.environ.get(f"AGENTPLANE_ACCEPTANCE_OPERATOR_{name}"):
            pytest.fail(
                f"BLOCKED: missing AGENTPLANE_ACCEPTANCE_OPERATOR_{name}; provision a dedicated operator's "
                "real BFF OIDC session and protected runner environment (acceptance README).",
                pytrace=False,
            )
    url = httpx.URL(base_url)
    if url.scheme != "https" or url.userinfo or url.query or url.fragment or url.path not in ("", "/"):
        pytest.fail("BLOCKED: BFF acceptance requires an HTTPS app origin without credentials or path", pytrace=False)
    cookie = SecretStr(os.environ["AGENTPLANE_ACCEPTANCE_OPERATOR_SESSION_COOKIE"])
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        cookies={SECURE_COOKIE: cookie.get_secret_value()},
        headers={"Origin": base_url.rstrip("/")},
        timeout=30,
        follow_redirects=False,
    ) as http:
        me = await http.get("/auth/me")
        if me.status_code != HTTPStatus.OK:
            pytest.fail("BLOCKED: dedicated operator BFF session absent or expired; log in again", pytrace=False)
        assert me.json() == {"username": os.environ["AGENTPLANE_ACCEPTANCE_OPERATOR_USERNAME"]}
        # An absent request exercises the actual federation dependency without listing other requests.
        probe = await http.get(f"/actions/{uuid4()}")
        if probe.status_code != HTTPStatus.NOT_FOUND or probe.json() != {
            "detail": "Action Service rejected the request"
        }:
            pytest.fail(
                f"BLOCKED: BFF Action federation preflight returned HTTP {probe.status_code}; "
                "dedicated operator session must be authorized for the configured target issuer/subject",
                pytrace=False,
            )
        yield http


class DecidedMcpReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    state: Literal["succeeded", "denied"]
    result: JsonValue


@pytest.mark.parametrize("verdict", list(Verdict))
async def test_agent_mcp_bff_decision(
    operator_bff: httpx.AsyncClient,
    client: Client,
    sandbox: Callable[..., Awaitable[SandboxView]],
    provider: Provider,
    model: str,
    verdict: Verdict,
) -> None:
    view = await sandbox(f"accept-mcp-{provider}-{verdict}")
    agent = await Agent.open(client, sandbox=view.name, provider=provider, model=model)
    # FixtureDecisionProvider auto-allows only messages of at most 200 characters.
    marker = f"MCP-BFF-{uuid4()}-" + "x" * 201
    submission_key = str(uuid4())
    submitted = await agent.run(f"""
Use the real Agentplane Actions HTTP API from your sandbox using HTTP tools or a shell.
Base URL: http://agentplane-actions.agentplane-staging.svc.cluster.local:8080
Use the public placeholder Authorization: Bearer {WORKLOAD_CREDENTIAL_PLACEHOLDER}.
The normal proxy supplies your workload identity. Never read a real token, bypass the
proxy, call an operator route, or connect directly to MCP.
GET /v1/action-groups and GET /v1/action-groups/everything/actions/echo to discover echo
and its message schema. Submit exactly once with POST /v1/action-requests:
{{"idempotency_key":"{submission_key}","action":{{"group":"everything","name":"echo"}},"arguments":{{"message":"{marker}"}}}}
The response must be decision_pending. Do NOT wait for a decision or poll in this turn.
Stop now and return ONLY the returned request UUID, without JSON, fences, or explanation.
""")
    request_id = UUID(submitted.answer.strip())
    assert submitted.answer.strip() == str(request_id)
    path = f"/actions/{request_id}"
    pending_response = await operator_bff.get(path)
    assert pending_response.status_code == HTTPStatus.OK
    pending = ActionRequestView.model_validate(pending_response.json())
    assert pending.id == request_id
    assert pending.idempotency_key == submission_key
    assert (pending.action.group, pending.action.name) == ("everything", "echo")
    assert pending.arguments == {"message": marker}
    assert pending.state is ActionState.DECISION_PENDING
    assert pending.version == 1
    assert pending.decision is None
    assert pending.execution is None

    decision = DecisionInput(verdict=verdict, expected_version=pending.version, idempotency_key=str(uuid4()))
    decided_response = await operator_bff.post(f"{path}/decision", json=decision.model_dump(mode="json"))
    assert decided_response.status_code == HTTPStatus.OK
    decided = ActionRequestView.model_validate(decided_response.json())
    assert decided.id == request_id
    assert decided.arguments == pending.arguments
    assert decided.version == pending.version + 1
    assert decided.decision is not None
    assert decided.decision.verdict is verdict
    assert decided.decision.provider == "human_operator"
    assert decided.decision.issuer == (
        f"{os.environ['AGENTPLANE_ACCEPTANCE_OPERATOR_ISSUER']}:{os.environ['AGENTPLANE_ACCEPTANCE_OPERATOR_SUBJECT']}"
    )
    assert decided.decision.idempotency_key == decision.idempotency_key
    expected_state = ActionState.SUCCEEDED if verdict is Verdict.ALLOW else ActionState.DENIED
    expected_result = {"content": [f"Echo: {marker}"]} if verdict is Verdict.ALLOW else None
    if verdict is Verdict.ALLOW:
        assert decided.state is ActionState.ALLOWED
        assert decided.execution is not None
    else:
        assert decided.state is ActionState.DENIED
        assert decided.execution is None

    completed = await agent.run(f"""
Resume the SAME Action request {request_id}; do not submit or decide anything.
Use the same agent-facing API and workload placeholder as before.
Poll GET /v1/action-requests/{request_id}/events?after_sequence=0 and
GET /v1/action-requests/{request_id} until terminal, advancing the events cursor
to the last sequence received and waiting briefly between polls. Stop on failure
or after 90 seconds without progress. Fetch the full events from after_sequence=0
at the end, checking contiguous sequences and the history from decision_pending
through denied, or allowed/dispatching/running/succeeded, without extra transitions.
Return ONLY strict JSON with exactly request_id, state, result. Copy result from
execution.result, or use null when denied with no execution. Do not fabricate it.
""")
    # Unlike Turn.report, reject fences and surrounding prose here.
    report = DecidedMcpReport.model_validate_json(completed.answer)
    assert report.request_id == request_id
    assert report.state == expected_state
    assert report.result == expected_result
    terminal_response = await operator_bff.get(path)
    assert terminal_response.status_code == HTTPStatus.OK
    terminal = ActionRequestView.model_validate(terminal_response.json())
    assert terminal.id == request_id
    assert terminal.idempotency_key == submission_key
    assert terminal.action == pending.action
    assert terminal.arguments == pending.arguments
    assert terminal.caller_principal == pending.caller_principal
    assert terminal.decision == decided.decision
    assert terminal.state is expected_state
    if verdict is Verdict.ALLOW:
        assert terminal.execution is not None
        assert decided.execution is not None
        assert terminal.execution.id == decided.execution.id
        assert terminal.execution.state is ExecutionState.SUCCEEDED
        assert terminal.execution.result == expected_result
        assert terminal.execution.error is None
    else:
        assert terminal.execution is None

    # Replay the original version/key after completion: same Decision and Execution, no new dispatch.
    duplicate = await operator_bff.post(f"{path}/decision", json=decision.model_dump(mode="json"))
    assert duplicate.status_code == HTTPStatus.OK
    assert ActionRequestView.model_validate(duplicate.json()) == terminal
    stale = decision.model_copy(update={"idempotency_key": str(uuid4())})
    refused = await operator_bff.post(f"{path}/decision", json=stale.model_dump(mode="json"))
    assert refused.status_code == HTTPStatus.CONFLICT
    unchanged = await operator_bff.get(path)
    assert unchanged.status_code == HTTPStatus.OK
    assert ActionRequestView.model_validate(unchanged.json()) == terminal


if __name__ == "__main__":
    pytest_bazel.main()
