"""Real staging agents discover, submit, poll and report an MCP-backed Action."""

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID, uuid4

import pytest_bazel
from pydantic import BaseModel, ConfigDict, JsonValue

from x.agentplane.acceptance.agent import Agent
from x.agentplane.action_service.client import WORKLOAD_CREDENTIAL_PLACEHOLDER
from x.agentplane.app.api import Provider
from x.agentplane.app.client import Client
from x.agentplane.app.inventory import SandboxView


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


if __name__ == "__main__":
    pytest_bazel.main()
