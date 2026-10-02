"""Headless authenticated session access: HTTP → Kubernetes identity/discovery → native runner."""

import asyncio
import json
import shlex
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

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
from agentplane.sandbox_service.inventory import SANDBOX_BINDING_ANNOTATION
from agentplane.sandbox_service.session_config import Harness, SandboxBinding, ThreadDefaults
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, TokenVerdict
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator
from agentplane.workload_auth.principal import WorkloadPrincipalResolver
from util.agent_sandbox import SANDBOXES_PLURAL

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
def resources(cluster: Cluster, runner: RunnerHandle) -> SessionResources:
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{SANDBOX_NAMESPACE}:{ACCOUNT}",
        pod_name="test-caller-pod",
        pod_uid="test-caller-pod-uid",
        audiences=(AUDIENCE,),
    )
    return SessionResources(
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


@pytest.fixture
async def api(resources: SessionResources) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(resources)),
        base_url="http://test-sandbox-service",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        yield client


@pytest.fixture
def managed_resources(resources: SessionResources) -> SessionResources:
    return replace(
        resources,
        manager_accounts=frozenset({ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name=ACCOUNT)}),
        platform_instructions="Test platform guidance.",
    )


@pytest.fixture
async def manager_api(managed_resources: SessionResources) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(managed_resources)),
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


def set_binding(cluster: Cluster, binding: SandboxBinding) -> None:
    cluster.fake.objects[SANDBOXES_PLURAL][SANDBOX]["metadata"].setdefault("annotations", {})[
        SANDBOX_BINDING_ANNOTATION
    ] = binding.model_dump_json()


async def wait_http_event(
    api: httpx.AsyncClient, destination: dict[str, object], *, after_cursor: int, kind: str
) -> event_log_pb2.EventEntry:
    async with asyncio.timeout(15):
        while True:
            response = await api.post(
                "/v1/sessions/follow", json={"destination": destination, "after_cursor": after_cursor}
            )
            assert response.status_code == 200, response.text
            for line in response.text.splitlines():
                if line.startswith("data: "):
                    entry = ParseDict(json.loads(line.removeprefix("data: ")), event_log_pb2.EventEntry())
                    after_cursor = entry.cursor
                    if events.kind(entry) == kind:
                        return entry
            await asyncio.sleep(0.01)


async def complete_guided_turn(
    api: httpx.AsyncClient, destination: dict[str, object], model: ScriptedModel, command_id: str
) -> None:
    response = await api.post(
        "/v1/sessions/commands",
        json={
            "destination": destination,
            "command": {"commandId": command_id, "submitInput": {"text": "Reply with exactly: GUIDANCE_OK"}},
        },
    )
    assert response.status_code == 200, response.text
    receipt = ParseDict(response.json(), event_log_pb2.EventEntry())
    request = await model.request()
    assert "Test platform guidance." in request.system_text
    assert "Test task guidance." in request.system_text
    assert "New platform guidance." not in request.system_text
    assert str(SANDBOX_UID) in request.system_text
    await model.reply(request, Text("GUIDANCE_OK"))
    await wait_http_event(api, destination, after_cursor=receipt.cursor, kind="turn_completed")


async def test_http_only_launch_and_resume_preserve_retained_configuration(
    manager_api: httpx.AsyncClient,
    managed_resources: SessionResources,
    model: ScriptedModel,
    cluster: Cluster,
    spec: protocol_pb2.SessionSpec,
    destination: dict[str, object],
    workspace: Path,
) -> None:
    bootstrap_marker = workspace / "bootstrap-runs"
    setup_marker = workspace / "setup-runs"
    binding = SandboxBinding(
        bootstrap=f"printf B >> {shlex.quote(str(bootstrap_marker))}",
        thread_defaults=ThreadDefaults(
            harness=Harness(protocol_pb2.Harness.Name(spec.harness)),
            model=spec.model,
            reasoning_effort=spec.reasoning_effort,
            cwd=spec.cwd,
            instructions="Test task guidance.",
            setup_script=f"printf S >> {shlex.quote(str(setup_marker))}",
        ),
    )
    set_binding(cluster, binding)
    sandbox_destination = {key: value for key, value in destination.items() if key != "session_id"}
    for _ in range(2):
        initialized = await manager_api.post("/v1/sandboxes/initialize", json={"destination": sandbox_destination})
        assert initialized.status_code == 200, initialized.text
        assert ParseDict(initialized.json(), protocol_pb2.InitializeResult()).exit_code == 0
    assert bootstrap_marker.read_text() == "B"
    opened = await manager_api.post("/v1/sessions/open", json={"destination": destination})
    assert opened.status_code == 200, opened.text
    attached = ParseDict(opened.json(), protocol_pb2.Attached())
    async with asyncio.timeout(15):
        while attached.harness_state != protocol_pb2.HARNESS_STATE_RUNNING:
            assert attached.setup_state not in (protocol_pb2.SETUP_STATE_FAILED, protocol_pb2.SETUP_STATE_INTERRUPTED)
            await asyncio.sleep(0.05)
            inspected = await manager_api.post("/v1/sessions/inspect", json={"destination": destination})
            assert inspected.status_code == 200, inspected.text
            attached = ParseDict(inspected.json(), protocol_pb2.Attached())
    assert attached.harness_state == protocol_pb2.HARNESS_STATE_RUNNING
    assert attached.setup_state == protocol_pb2.SETUP_STATE_SUCCEEDED
    assert "Test platform guidance." in attached.spec.instructions
    assert "Test task guidance." in attached.spec.instructions
    assert str(destination["session_id"]) in attached.spec.instructions
    assert str(SANDBOX_UID) in attached.spec.instructions
    repeated = await manager_api.post("/v1/sessions/open", json={"destination": destination})
    assert repeated.status_code == 200, repeated.text
    assert ParseDict(repeated.json(), protocol_pb2.Attached()).spec == attached.spec
    assert bootstrap_marker.read_text() == "B"
    assert setup_marker.read_text() == "S"
    conflicting = await manager_api.post(
        "/v1/sessions/open", json={"destination": destination, "spec": {"instructions": "Different task"}}
    )
    assert conflicting.status_code == 409
    # Native harnesses must persist a real conversation before they can resume it.
    await complete_guided_turn(manager_api, destination, model, "test-http-seed")
    stopped = await manager_api.post(
        "/v1/sessions/commands",
        json={"destination": destination, "command": {"commandId": "test-http-stop", "stopRunnerSession": {}}},
    )
    assert stopped.status_code == 200, stopped.text
    stop_receipt = ParseDict(stopped.json(), event_log_pb2.EventEntry())
    await wait_http_event(manager_api, destination, after_cursor=stop_receipt.cursor, kind="harness_exited")
    set_binding(cluster, SandboxBinding(bootstrap="exit 42", thread_defaults=ThreadDefaults(model="changed")))
    # A restarted service with different configuration must not rewrite the retained native spec,
    # rerun bootstrap/setup, or need an app record to recover this session.
    changed = replace(managed_resources, platform_instructions="New platform guidance.")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(changed)),
        base_url="http://test-sandbox-service",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as restarted:
        resumed = await restarted.post("/v1/sessions/resume", json={"destination": destination})
        assert resumed.status_code == 200, resumed.text
        recovered = ParseDict(resumed.json(), protocol_pb2.Attached())
        assert recovered.harness_state == protocol_pb2.HARNESS_STATE_RUNNING
        assert recovered.spec == attached.spec
        await complete_guided_turn(restarted, destination, model, "test-http-resumed")
        listed = await restarted.post("/v1/sessions/list", json={"destination": sandbox_destination})
        assert listed.status_code == 200
        rows = listed.json()["sessions"]
        assert len(rows) == 1
        assert ParseDict(rows[0], protocol_pb2.SessionSummary()).spec == attached.spec
        # The current binding now names a different bootstrap. Explicit initialization conflicts,
        # rather than rerunning it or pretending the original Sandbox initialization was replaced.
        conflict = await restarted.post("/v1/sandboxes/initialize", json={"destination": sandbox_destination})
        assert conflict.status_code == 409, conflict.text
    assert bootstrap_marker.read_text() == "B"
    assert setup_marker.read_text() == "S"


async def test_explicit_resume_never_creates(
    manager_api: httpx.AsyncClient, destination: dict[str, object], client: RunnerClient
) -> None:
    response = await manager_api.post("/v1/sessions/resume", json={"destination": destination})
    assert response.status_code == 409
    assert not await client.list_sessions()


async def test_delivery_authority_does_not_grant_management(
    api: httpx.AsyncClient, destination: dict[str, object], cluster: Cluster
) -> None:
    sandbox_destination = {key: value for key, value in destination.items() if key != "session_id"}
    for route, target in (
        ("/v1/sessions/open", destination),
        ("/v1/sessions/resume", destination),
        ("/v1/sandboxes/initialize", sandbox_destination),
    ):
        response = await api.post(route, json={"destination": target})
        assert response.status_code == 403, response.text
    assert cluster.fake.pod_reads == 0


@pytest.mark.parametrize("manager", [False, True])
async def test_cross_owner_management_requires_both_grants(
    resources: SessionResources, cluster: Cluster, destination: dict[str, object], manager: bool
) -> None:
    account = ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="test-control-service")
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{account.namespace}:{account.name}",
        pod_name="test-control-pod",
        pod_uid="test-control-pod-uid",
        audiences=(AUDIENCE,),
    )
    configured = replace(
        resources,
        destinations=replace(resources.destinations, trusted_accounts=frozenset() if manager else frozenset({account})),
        manager_accounts=frozenset({account}) if manager else frozenset(),
        platform_instructions="Test guidance",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(configured)),
        base_url="http://test-sandbox-service",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as caller:
        response = await caller.post("/v1/sessions/open", json={"destination": destination})
        assert response.status_code == 403, response.text
    assert cluster.fake.pod_reads == 0


async def test_failed_setup_cannot_be_resumed(
    manager_api: httpx.AsyncClient, destination: dict[str, object], spec: protocol_pb2.SessionSpec
) -> None:
    opened = await manager_api.post(
        "/v1/sessions/open", json={"destination": destination, "spec": MessageToDict(spec), "setup_script": "exit 42"}
    )
    assert opened.status_code == 200, opened.text
    attached = ParseDict(opened.json(), protocol_pb2.Attached())
    async with asyncio.timeout(15):
        while attached.setup_state == protocol_pb2.SETUP_STATE_RUNNING:
            await asyncio.sleep(0.05)
            inspected = await manager_api.post("/v1/sessions/inspect", json={"destination": destination})
            assert inspected.status_code == 200, inspected.text
            attached = ParseDict(inspected.json(), protocol_pb2.Attached())
    assert attached.setup_state == protocol_pb2.SETUP_STATE_FAILED
    resumed = await manager_api.post("/v1/sessions/resume", json={"destination": destination})
    assert resumed.status_code == 409, resumed.text


async def test_invalid_launch_and_failed_bootstrap_never_create(
    manager_api: httpx.AsyncClient,
    destination: dict[str, object],
    cluster: Cluster,
    client: RunnerClient,
    spec: protocol_pb2.SessionSpec,
) -> None:
    for invalid in ({}, {"unknownField": True}, {"harness": "HARNESS_CODEX", "model": "m"}):
        response = await manager_api.post("/v1/sessions/open", json={"destination": destination, "spec": invalid})
        assert response.status_code == 422, response.text
    set_binding(cluster, SandboxBinding(bootstrap="exit 42"))
    failed = await manager_api.post("/v1/sessions/open", json={"destination": destination, "spec": MessageToDict(spec)})
    assert failed.status_code == 409, failed.text
    assert not await client.list_sessions()


if __name__ == "__main__":
    pytest_bazel.main()
