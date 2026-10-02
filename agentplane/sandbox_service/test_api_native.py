"""Headless authenticated session access: HTTP → Kubernetes identity/discovery → native runner."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_bazel
from google.protobuf.json_format import MessageToDict, ParseDict
from kubernetes_asyncio import client as k8s_client

from agentplane.protocol import command_pb2, event_log_pb2
from agentplane.runner import protocol_pb2
from agentplane.runner.client import RunnerClient
from agentplane.runner.conftest import RunnerHandle
from agentplane.runner.testing import events
from agentplane.runner.testing.scripted_model import ScriptedModel, Text
from agentplane.sandbox_service.api import SessionResources, create_app
from agentplane.sandbox_service.destinations import DestinationResolver, SessionDestination
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, TokenVerdict
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator
from agentplane.workload_auth.principal import WorkloadPrincipalResolver

# gazelle:include_dep @pypi//protobuf

TOKEN = "test-session-workload-token"
AUDIENCE = "test-sandbox-service"


@pytest.fixture
def destination() -> dict[str, object]:
    return SessionDestination(
        owner=ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name=ACCOUNT),
        sandbox=SANDBOX,
        sandbox_uid=SANDBOX_UID,
        session_id="test-api-session",
    ).model_dump(mode="json")


@pytest.fixture
async def api(cluster: Cluster, runner: RunnerHandle) -> AsyncIterator[httpx.AsyncClient]:
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{SANDBOX_NAMESPACE}:{ACCOUNT}",
        pod_name="test-caller-pod",
        pod_uid="test-caller-pod-uid",
        audiences=(AUDIENCE,),
    )
    app = create_app(
        SessionResources(
            authenticate=WorkloadPrincipalAuthenticator(
                WorkloadPrincipalResolver(
                    authentication=k8s_client.AuthenticationV1Api(cluster.api),
                    audience=AUDIENCE,
                    allowed_service_account_namespaces={SANDBOX_NAMESPACE},
                )
            ),
            destinations=DestinationResolver(cluster.inventory, k8s_client.CoreV1Api(cluster.api), runner.port),
            follow_lease_s=0.2,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test-sandbox-service",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        yield client


async def test_admission_and_follow_preserve_runner_evidence_without_app(
    api: httpx.AsyncClient,
    client: RunnerClient,
    model: ScriptedModel,
    spec: protocol_pb2.SessionSpec,
    destination: dict[str, object],
) -> None:
    # Backend-native setup, not an app Thread, app database, or UI prompt/bootstrap operation.
    async with await client.attach("test-api-session", spec=spec) as observer:
        inspected = await api.post("/v1/sessions/inspect", json={"destination": destination})
        assert inspected.status_code == 200
        assert inspected.json()["harnessState"] == "HARNESS_STATE_RUNNING"
        command = command_pb2.Command(
            command_id="test-inbox-notice", submit_input=command_pb2.SubmitInput(text="Reply with exactly: API_OK")
        )
        submitted = await api.post(
            "/v1/sessions/commands", json={"destination": destination, "command": MessageToDict(command)}
        )
        assert submitted.status_code == 200, submitted.text
        receipt = ParseDict(submitted.json(), event_log_pb2.EventEntry())
        assert receipt.event.command_admitted.command == command
        # Reconcile an uncertain submission through the same API, without allocating a new ID.
        replay = await api.post(
            "/v1/sessions/commands", json={"destination": destination, "command": MessageToDict(command)}
        )
        assert replay.json() == submitted.json()
        followed = await api.post("/v1/sessions/follow", json={"destination": destination})
        assert followed.status_code == 200
        entries = [
            ParseDict(json.loads(line.removeprefix("data: ")), event_log_pb2.EventEntry())
            for line in followed.text.splitlines()
            if line.startswith("data: ")
        ]
        assert receipt in entries
        # Reconnect cursors are the runner's own, not an independent HTTP delivery sequence.
        tail = await api.post(
            "/v1/sessions/follow", json={"destination": destination, "after_cursor": entries[-1].cursor}
        )
        assert tail.status_code == 200
        assert all(
            int(json.loads(line.removeprefix("data: "))["cursor"]) > entries[-1].cursor
            for line in tail.text.splitlines()
            if line.startswith("data: ")
        )
        await model.reply(await model.request(), Text("API_OK"))
        await observer.until(events.turn_completed)
        assert events.of_kind(observer.seen, "command_admitted") == [receipt]


async def test_read_and_command_never_create_or_resume(
    api: httpx.AsyncClient, client: RunnerClient, spec: protocol_pb2.SessionSpec, destination: dict[str, object]
) -> None:
    missing = await api.post("/v1/sessions/inspect", json={"destination": destination})
    assert missing.status_code == 409
    assert not await client.list_sessions()
    observer = await client.attach("test-api-session", spec=spec)
    try:
        await observer.stop_runner_session("test-stop")
        await observer.drain_until_end()
    finally:
        observer.cancel()
    inspected = await api.post("/v1/sessions/inspect", json={"destination": destination})
    assert inspected.json()["harnessState"] == "HARNESS_STATE_STOPPED"
    refused = await api.post(
        "/v1/sessions/commands",
        json={"destination": destination, "command": {"commandId": "test-no-wake", "submitInput": {"text": "No wake"}}},
    )
    assert refused.status_code == 409
    assert (await client.list_sessions())[0].harness_state == protocol_pb2.HARNESS_STATE_STOPPED


async def test_token_revocation_and_forged_identity_fail_before_runner_access(
    api: httpx.AsyncClient, destination: dict[str, object], cluster: Cluster
) -> None:
    forged = {**destination, "owner": {"namespace": SANDBOX_NAMESPACE, "name": "test-someone-else"}}
    denied = await api.post(
        "/v1/sessions/inspect", json={"destination": forged}, headers={"X-ServiceAccount": "test-someone-else"}
    )
    assert denied.status_code == 403
    assert cluster.fake.pod_reads == 0
    cluster.fake.tokens.clear()
    revoked = await api.post("/v1/sessions/inspect", json={"destination": destination})
    assert revoked.status_code == 401
    assert cluster.fake.pod_reads == 0
    assert cluster.fake.token_reviews == 2


async def test_invalid_command_is_not_submitted(
    api: httpx.AsyncClient, destination: dict[str, object], client: RunnerClient, spec: protocol_pb2.SessionSpec
) -> None:
    async with await client.attach("test-api-session", spec=spec) as observer:
        for command in ({}, {"commandId": "test-missing-operation"}, {"notACommandField": True}):
            response = await api.post("/v1/sessions/commands", json={"destination": destination, "command": command})
            assert response.status_code == 422
        await observer.detach()
        await observer.drain_until_end()
        assert not events.of_kind(observer.seen, "command_admitted")


if __name__ == "__main__":
    pytest_bazel.main()
