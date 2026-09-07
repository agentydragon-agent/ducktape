"""Independent workload reads, not an LLM's transcription of HTTP responses.

Controlled-host only: exec curl in the suite-owned runner through its normal sidecar.
No projected token is read, no port-forward bypasses auth, and no cluster config is edited.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import JsonValue, TypeAdapter

from util.testing.undeclared_outputs import undeclared_outputs_dir
from x.agentplane.action_service.client import WORKLOAD_CREDENTIAL_PLACEHOLDER
from x.agentplane.action_service.models import ActionEventView, ActionRequestView, ActionState

ACTIONS_URL = "http://agentplane-actions.agentplane-staging.svc.cluster.local:8080"
JSON = TypeAdapter(JsonValue)
REQUESTS = TypeAdapter(list[ActionRequestView])
EVENTS = TypeAdapter(list[ActionEventView])


@dataclass
class ActionEvidence:
    sandbox: str
    exchanges: list[dict[str, JsonValue]] = field(default_factory=list)

    async def get(self, path: str) -> JsonValue:
        # Proxy env is configured for harness children, not kubectl exec. Explicitly use the
        # same sidecar port from sandboxtemplate-agentplane-runner.yaml; never bypass it.
        command = [
            "kubectl",
            "-n",
            os.environ.get("AGENTPLANE_ACCEPTANCE_NAMESPACE", "agentplane-staging"),
            "exec",
            self.sandbox,
            "-c",
            "runner",
            "--",
            "/usr/bin/curl",
            "--silent",
            "--show-error",
            "--max-time",
            "20",
            "--proxy",
            "http://127.0.0.1:3128",
            "--noproxy",
            "",
            "--header",
            f"Authorization: Bearer {WORKLOAD_CREDENTIAL_PLACEHOLDER}",
            "--write-out",
            "\n%{http_code}",
            f"{ACTIONS_URL}{path}",
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise AssertionError(f"independent observer timed out: {self.sandbox} {path}") from None
        # Do not dump arbitrary pod/process output into artifacts. Successful Action projections
        # are the service's redacted wire contract; transport failures report status, not bodies.
        assert process.returncode == 0, f"observer exec/curl failed: {self.sandbox} {path} exit={process.returncode}"
        body, status = stdout.decode().rsplit("\n", 1)
        assert status == "200", f"observer {self.sandbox} GET {path}: HTTP {status}; check workload auth/RBAC/route"
        result = JSON.validate_json(body)
        self.exchanges.append({"path": path, "body": result})
        (undeclared_outputs_dir() / f"{self.sandbox}-actions.json").write_text(json.dumps(self.exchanges, indent=2))
        return result

    async def requests(self) -> list[ActionRequestView]:
        return REQUESTS.validate_python(await self.get("/v1/action-requests"))

    async def request(self, request_id: UUID) -> ActionRequestView:
        return ActionRequestView.model_validate(await self.get(f"/v1/action-requests/{request_id}"))

    async def events(self, request_id: UUID) -> list[ActionEventView]:
        return EVENTS.validate_python(await self.get(f"/v1/action-requests/{request_id}/events?after_sequence=0"))


def assert_history(events: list[ActionEventView], states: list[ActionState]) -> None:
    assert [event.state for event in events] == states, events
    assert [event.sequence for event in events] == list(range(1, len(events) + 1)), events


def assert_success(request: ActionRequestView, events: list[ActionEventView], message: str) -> UUID:
    assert request.state == ActionState.SUCCEEDED, request
    assert request.execution is not None, request
    assert request.execution.state == "succeeded", request
    assert request.execution.result == {"content": [f"Echo: {message}"]}, request
    assert_history(
        events,
        [
            ActionState.DECISION_PENDING,
            ActionState.ALLOWED,
            ActionState.DISPATCHING,
            ActionState.RUNNING,
            ActionState.SUCCEEDED,
        ],
    )
    return request.execution.id


def assert_unexecuted(request: ActionRequestView, events: list[ActionEventView], *, denied: bool) -> None:
    states = [ActionState.DECISION_PENDING]
    if denied:
        states.append(ActionState.DENIED)
        assert request.decision is not None, request
        assert request.decision.verdict == "deny", request
    else:
        assert request.decision is None, request
    assert request.state == states[-1], request
    assert request.execution is None, request
    assert_history(events, states)
