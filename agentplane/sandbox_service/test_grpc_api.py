"""Real gRPC and TokenReview, with a controllable runner peer for transport failure edges."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4

import grpc
import pytest
import pytest_bazel
from google.protobuf.empty_pb2 import Empty
from kubernetes_asyncio import client as k8s_client

from agentplane.protocol import command_pb2, event_log_pb2, event_pb2
from agentplane.runner import protocol_pb2 as runner_pb2
from agentplane.runner.client import RunnerError, StreamClosedError
from agentplane.sandbox_service import protocol_pb2, wire
from agentplane.sandbox_service.client import FollowLeaseExpiredError, SandboxServiceClient, ServiceError
from agentplane.sandbox_service.destinations import DestinationResolver
from agentplane.sandbox_service.models import ProvisioningState, SandboxDestination
from agentplane.sandbox_service.grpc_api import Resources
from agentplane.sandbox_service.kubernetes_views import KUBERNETES_GRANTS_ANNOTATION, KUBERNETES_GRANTS_READY_ANNOTATION, PROVISIONING_ANNOTATION
from agentplane.sandbox_service.kubernetes_grants import ResolvedGrant, RoleBindingGrant, RoleRef
from agentplane.sandbox_service.testing.grpc_service import service_client
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, TokenVerdict
from agentplane.workload_auth.principal import WorkloadPrincipalResolver
from util.agent_sandbox import SANDBOXES_PLURAL

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep @pypi//grpcio

TOKEN = "test-grpc-token"
AUDIENCE = "test-sandbox-service"
OWNER = ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name=ACCOUNT)
DESTINATION = SandboxDestination(owner=OWNER, sandbox=SANDBOX, sandbox_uid=SANDBOX_UID)


@dataclass
class PeerAttachment:
    opened: runner_pb2.Open
    commands: asyncio.Queue[runner_pb2.ClientMessage] = field(default_factory=asyncio.Queue)
    responses: asyncio.Queue[runner_pb2.ServerMessage | grpc.StatusCode | None] = field(default_factory=asyncio.Queue)
    closed: asyncio.Event = field(default_factory=asyncio.Event)


class Peer:
    def __init__(self) -> None:
        self.attachments: asyncio.Queue[PeerAttachment] = asyncio.Queue()
        self.port = 0
        self.state = runner_pb2.HARNESS_STATE_RUNNING

    async def attach(
        self, requests: AsyncIterator[runner_pb2.ClientMessage], context: grpc.aio.ServicerContext
    ) -> AsyncIterator[runner_pb2.ServerMessage]:
        first = await anext(requests)
        connection = PeerAttachment(first.open)
        self.attachments.put_nowait(connection)

        async def consume() -> None:
            async for request in requests:
                connection.commands.put_nowait(request)

        consumer = asyncio.create_task(consume())
        try:
            yield runner_pb2.ServerMessage(
                attached=runner_pb2.Attached(session_id=first.open.session_id, harness_state=self.state)
            )
            while (message := await connection.responses.get()) is not None:
                if isinstance(message, grpc.StatusCode):
                    await context.abort(message, "test runner failure")
                else:
                    yield message
        finally:
            consumer.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await consumer
            finally:
                # Aborting the server RPC can also fail its request-reader task. Still record
                # completed cleanup, rather than making the test wait on an unreachable marker.
                connection.closed.set()


@pytest.fixture
async def peer() -> AsyncIterator[Peer]:
    peer = Peer()
    server = grpc.aio.server()
    server.add_generic_rpc_handlers(
        [
            grpc.method_handlers_generic_handler(
                "ducktape.agentplane.runner.v1.Runner",
                {
                    "Attach": grpc.stream_stream_rpc_method_handler(
                        peer.attach,
                        request_deserializer=runner_pb2.ClientMessage.FromString,
                        response_serializer=runner_pb2.ServerMessage.SerializeToString,
                    )
                },
            )
        ]
    )
    peer.port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield peer
    finally:
        await server.stop(0)


@pytest.fixture
def resources(cluster: Cluster, peer: Peer) -> Resources:
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{OWNER.namespace}:{OWNER.name}",
        pod_name="test-caller",
        pod_uid="test-caller-uid",
        audiences=(AUDIENCE,),
    )
    return Resources(
        principals=WorkloadPrincipalResolver(
            authentication=k8s_client.AuthenticationV1Api(cluster.api),
            audience=AUDIENCE,
            allowed_service_account_namespaces={SANDBOX_NAMESPACE},
        ),
        destinations=DestinationResolver(cluster.inventory, k8s_client.CoreV1Api(cluster.api), peer.port),
        follow_lease_s=0.5,
        admission_timeout_s=1,
    )


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token"
    path.write_text(TOKEN)
    return path


@pytest.fixture
async def remote(resources: Resources, token_file: Path) -> AsyncIterator[SandboxServiceClient]:
    async with service_client(resources, token_file) as client:
        yield client


def admission(command: command_pb2.Command, cursor: int) -> event_log_pb2.EventEntry:
    return event_log_pb2.EventEntry(
        cursor=cursor,
        origin=event_log_pb2.EventOrigin(source_id="test-journal", sequence=cursor),
        event=event_pb2.Event(command_admitted=event_pb2.CommandAdmitted(command=command)),
    )


async def test_admission_is_exact_native_evidence(remote: SandboxServiceClient, peer: Peer) -> None:
    command = command_pb2.Command(command_id="notice", submit_input=command_pb2.SubmitInput(text="7 messages"))
    async with asyncio.timeout(8), asyncio.TaskGroup() as tasks:
        pending = tasks.create_task(remote.runner(DESTINATION).command("session", command, after_cursor=4))
        connection = await peer.attachments.get()
        assert connection.opened.follow.after_cursor == 4
        assert not connection.opened.HasField("spec")
        assert (await connection.commands.get()).command == command
        assert (await connection.commands.get()).HasField("detach")
        wrong = command_pb2.Command(command_id="notice", submit_input=command_pb2.SubmitInput(text="different"))
        connection.responses.put_nowait(runner_pb2.ServerMessage(event_entry=admission(wrong, 5)))
        assert not pending.done()
        receipt = admission(command, 6)
        connection.responses.put_nowait(runner_pb2.ServerMessage(event_entry=receipt))
        assert await pending == receipt
        await connection.closed.wait()


async def test_follow_reconnect_rechecks_token_and_preserves_cursor(
    remote: SandboxServiceClient, peer: Peer, cluster: Cluster
) -> None:
    async with asyncio.timeout(8):
        runner = remote.runner(DESTINATION)
        attachment = await runner.attach("session", after_cursor=11)
        connection = await peer.attachments.get()
        assert connection.opened.follow.after_cursor == 11
        assert attachment.attached.session_id == "session"
        receipt = admission(command_pb2.Command(command_id="recorded"), 12)
        connection.responses.put_nowait(runner_pb2.ServerMessage(event_entry=receipt))
        assert await attachment.next_entry() == receipt
        with pytest.raises(FollowLeaseExpiredError):
            await attachment.next_entry()
        await connection.closed.wait()
        second = await runner.attach("session", after_cursor=12)
        next_connection = await peer.attachments.get()
        assert next_connection.opened.follow.after_cursor == 12
        second.cancel()
        await next_connection.closed.wait()
        # Rotation is read per request; a stale or revoked credential cannot reuse the channel's identity.
        remote.token_file.write_text("invalid-token")
        with pytest.raises(ServiceError) as rejected:
            await runner.attach("session", after_cursor=12)
        assert rejected.value.code == grpc.StatusCode.UNAUTHENTICATED
        assert peer.attachments.empty()
        remote.token_file.write_text(TOKEN)
        cluster.fake.tokens.clear()
        with pytest.raises(ServiceError) as revoked:
            await runner.attach("session", after_cursor=12)
        assert revoked.value.code == grpc.StatusCode.UNAUTHENTICATED
        assert peer.attachments.empty()


@pytest.mark.parametrize("ending", [None, grpc.StatusCode.UNAVAILABLE])
async def test_native_eof_is_distinct_from_backend_failure(
    remote: SandboxServiceClient, peer: Peer, ending: grpc.StatusCode | None
) -> None:
    async with asyncio.timeout(8):
        attachment = await remote.runner(DESTINATION).attach("session")
        connection = await peer.attachments.get()
        connection.responses.put_nowait(ending)
        if ending is None:
            with pytest.raises(StreamClosedError):
                await attachment.next_entry()
        else:
            with pytest.raises(ServiceError) as unavailable:
                await attachment.next_entry()
            assert unavailable.value.code == grpc.StatusCode.UNAVAILABLE
        await connection.closed.wait()


async def test_cancellation_closes_runner_attachment(remote: SandboxServiceClient, peer: Peer) -> None:
    async with asyncio.timeout(8):
        attachment = await remote.runner(DESTINATION).attach("session")
        connection = await peer.attachments.get()
        attachment.cancel()
        await connection.closed.wait()


async def test_timeout_is_uncertain_and_closes_attachment(remote: SandboxServiceClient, peer: Peer) -> None:
    command = command_pb2.Command(command_id="uncertain", submit_input=command_pb2.SubmitInput(text="hi"))

    async def submit() -> None:
        with pytest.raises(TimeoutError):
            await remote.runner(DESTINATION).command("session", command, after_cursor=0)

    async with asyncio.timeout(8), asyncio.TaskGroup() as tasks:
        pending = tasks.create_task(submit())
        connection = await peer.attachments.get()
        assert (await connection.commands.get()).command == command
        await pending
        await connection.closed.wait()
        assert peer.attachments.empty()  # The client did not retry the uncertain mutation.


async def test_stopped_command_does_not_send_input(remote: SandboxServiceClient, peer: Peer) -> None:
    peer.state = runner_pb2.HARNESS_STATE_STOPPED
    command = command_pb2.Command(command_id="stopped", submit_input=command_pb2.SubmitInput(text="hi"))
    async with asyncio.timeout(8):
        with pytest.raises(RunnerError):
            await remote.runner(DESTINATION).command("session", command, after_cursor=0)
        connection = await peer.attachments.get()
        await connection.closed.wait()
        assert not connection.opened.HasField("spec")
        assert connection.commands.empty()


@pytest.mark.parametrize(
    "metadata",
    [
        (),
        (("authorization", "Bearer invalid"),),
        (("authorization", f"Bearer {TOKEN}"), ("authorization", f"Bearer {TOKEN}")),
    ],
)
async def test_missing_invalid_or_duplicate_bearer_is_rejected(
    remote: SandboxServiceClient, peer: Peer, metadata: tuple[tuple[str, str], ...]
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as rejected:
        await remote.stub.InspectSession(
            protocol_pb2.SessionRequest(destination=wire.session_proto(DESTINATION, "session")), metadata=metadata
        )
    assert rejected.value.code() == grpc.StatusCode.UNAUTHENTICATED
    assert peer.attachments.empty()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"owner": ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="other")}, grpc.StatusCode.PERMISSION_DENIED),
        ({"sandbox_uid": uuid4()}, grpc.StatusCode.NOT_FOUND),
    ],
)
async def test_destination_authority_and_incarnation(
    remote: SandboxServiceClient, peer: Peer, change: dict[str, object], code: grpc.StatusCode
) -> None:
    with pytest.raises(ServiceError) as rejected:
        await remote.runner(DESTINATION.model_copy(update=change)).attach("session")
    assert rejected.value.code == code
    assert peer.attachments.empty()


async def test_management_requires_explicit_authority(
    remote: SandboxServiceClient, peer: Peer, cluster: Cluster
) -> None:
    destination = wire.session_proto(DESTINATION, "session")
    for call, request in (
        (remote.stub.OpenSession, protocol_pb2.OpenSessionRequest(destination=destination)),
        (remote.stub.ResumeSession, protocol_pb2.SessionRequest(destination=destination)),
        (remote.stub.InitializeSandbox, protocol_pb2.SandboxRequest(destination=destination.sandbox)),
        (remote.stub.ListSandboxes, Empty()),
    ):
        with pytest.raises(ServiceError) as rejected:
            await remote.unary(call, request)
        assert rejected.value.code == grpc.StatusCode.PERMISSION_DENIED
    assert cluster.fake.pod_reads == 0
    assert peer.attachments.empty()


@pytest.mark.parametrize("manager", [False, True])
async def test_cross_owner_management_requires_both_grants(
    resources: Resources, token_file: Path, cluster: Cluster, peer: Peer, manager: bool
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
    async with service_client(configured, token_file) as caller:
        with pytest.raises(ServiceError) as rejected:
            await caller.runner(DESTINATION).open("session", {})
        assert rejected.value.code == grpc.StatusCode.PERMISSION_DENIED
    assert cluster.fake.pod_reads == 0
    assert peer.attachments.empty()


@pytest.mark.parametrize("pending_launch", [False, True])
async def test_open_and_resume_refuse_unready_grants_without_app(
    resources: Resources, token_file: Path, cluster: Cluster, peer: Peer, pending_launch: bool
) -> None:
    annotations = cluster.fake.objects[SANDBOXES_PLURAL][SANDBOX]["metadata"].setdefault("annotations", {})
    if pending_launch:
        annotations[PROVISIONING_ANNOTATION] = "{}"
    else:
        grant = ResolvedGrant(
            name="config",
            grant=RoleBindingGrant(
                kind="RoleBinding", namespace=SANDBOX_NAMESPACE, role_ref=RoleRef(kind="Role", name="config-reader")
            ),
        )
        annotations[KUBERNETES_GRANTS_ANNOTATION] = json.dumps([grant.model_dump(mode="json")])
        annotations[KUBERNETES_GRANTS_READY_ANNOTATION] = "false"
    assert (await cluster.inventory.get(SANDBOX)).state is ProvisioningState.WAITING_FOR_GRANTS
    configured = replace(resources, manager_accounts=frozenset({OWNER}), platform_instructions="Test guidance")
    async with service_client(configured, token_file) as caller:
        runner = caller.runner(DESTINATION)
        with pytest.raises(ServiceError) as opened:
            await runner.open("session", {"harness": "HARNESS_CODEX", "cwd": "/w", "model": "test"})
        assert opened.value.code == grpc.StatusCode.UNAVAILABLE
        with pytest.raises(ServiceError) as resumed:
            await runner.resume("session")
        assert resumed.value.code == grpc.StatusCode.UNAVAILABLE
    assert peer.attachments.empty()


@pytest.mark.parametrize(
    "command",
    [
        command_pb2.Command(),
        command_pb2.Command(command_id="missing-operation"),
        command_pb2.Command(submit_input=command_pb2.SubmitInput(text="missing-id")),
    ],
)
async def test_invalid_command_is_not_submitted(
    remote: SandboxServiceClient, peer: Peer, cluster: Cluster, command: command_pb2.Command
) -> None:
    with pytest.raises(ServiceError) as rejected:
        await remote.runner(DESTINATION).command("session", command, after_cursor=0)
    assert rejected.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert cluster.fake.pod_reads == 0
    assert peer.attachments.empty()


async def test_wire_preserves_inventory_and_explicit_empty_overrides(cluster: Cluster) -> None:
    view = await cluster.inventory.get(SANDBOX)
    assert wire.sandbox_view(wire.sandbox_proto(view)) == view
    request = wire.open_proto(
        wire.session_proto(DESTINATION, "session"),
        {"model": "test-model", "instructions": "", "reasoningEffort": ""},
        "",
    )
    assert wire.launch_overrides(request) == {"model": "test-model", "instructions": "", "reasoningEffort": ""}
    assert request.HasField("setup_script")
    assert request.setup_script == ""
    request.override_mask.paths.append("unknown")
    with pytest.raises(ValueError, match="unique SessionSpec field names"):
        wire.launch_overrides(request)
    request.override_mask.paths[:] = ["model"]
    request.spec.cwd = "/unselected"
    with pytest.raises(ValueError, match="every supplied SessionSpec field"):
        wire.launch_overrides(request)


async def test_bare_service_eof_is_not_native_closure(tmp_path: Path) -> None:
    async def truncated(
        request: protocol_pb2.FollowSessionRequest, context: grpc.aio.ServicerContext
    ) -> AsyncIterator[protocol_pb2.FollowSessionResponse]:
        yield protocol_pb2.FollowSessionResponse(
            attached=runner_pb2.Attached(session_id=request.destination.session_id)
        )
        # Deliberately no ended observation: even an OK transport status is not native EOF evidence.

    server = grpc.aio.server()
    server.add_generic_rpc_handlers(
        [
            grpc.method_handlers_generic_handler(
                "ducktape.agentplane.sandbox.v1.SandboxService",
                {
                    "FollowSession": grpc.unary_stream_rpc_method_handler(
                        truncated,
                        request_deserializer=protocol_pb2.FollowSessionRequest.FromString,
                        response_serializer=protocol_pb2.FollowSessionResponse.SerializeToString,
                    )
                },
            )
        ]
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN)
    client = SandboxServiceClient(f"127.0.0.1:{port}", namespace=SANDBOX_NAMESPACE, token_file=token_file)
    try:
        attachment = await client.runner(DESTINATION).attach("session")
        try:
            with pytest.raises(ConnectionError, match="without native closure"):
                await attachment.next_entry()
        finally:
            attachment.cancel()
    finally:
        await client.close()
        await server.stop(0)


def test_duplicate_spec_aliases_are_refused() -> None:
    with pytest.raises(ValueError, match="both proto and JSON"):
        wire.open_proto(
            wire.session_proto(DESTINATION, "session"), {"reasoning_effort": "low", "reasoningEffort": "high"}, None
        )


if __name__ == "__main__":
    pytest_bazel.main()
