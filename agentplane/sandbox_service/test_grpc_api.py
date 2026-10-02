"""Real gRPC and TokenReview, with a controllable runner peer for transport failure edges."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import grpc
import pytest
import pytest_bazel
from google.protobuf.empty_pb2 import Empty

from agentplane.protocol import command_pb2, event_log_pb2, event_pb2
from agentplane.runner import protocol_pb2 as runner_pb2
from agentplane.runner.client import RunnerError, StreamClosedError
from agentplane.sandbox_service import protocol_pb2, wire
from agentplane.sandbox_service.client import FollowLeaseExpired, SandboxServiceClient, ServiceError
from agentplane.sandbox_service.destinations import DestinationResolver, SandboxDestination
from agentplane.sandbox_service.grpc_api import Resources
from agentplane.sandbox_service.testing.grpc_service import service
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, TokenVerdict
from agentplane.workload_auth.principal import WorkloadPrincipalResolver
from kubernetes_asyncio import client as k8s_client

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
        self, requests: AsyncIterator[runner_pb2.ClientMessage], context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[runner_pb2.ServerMessage]:
        first = await anext(requests)
        connection = PeerAttachment(first.open)
        self.attachments.put_nowait(connection)

        async def consume() -> None:
            async for request in requests:
                connection.commands.put_nowait(request)

        consumer = asyncio.create_task(consume())
        try:
            yield runner_pb2.ServerMessage(attached=runner_pb2.Attached(session_id=first.open.session_id, harness_state=self.state))
            while (message := await connection.responses.get()) is not None:
                if isinstance(message, grpc.StatusCode):
                    await context.abort(message, "test runner failure")
                else:
                    yield message
        finally:
            consumer.cancel()
            with suppress(asyncio.CancelledError):
                await consumer
            connection.closed.set()


@pytest.fixture
async def peer() -> AsyncIterator[Peer]:
    peer = Peer()
    server = grpc.aio.server()
    server.add_generic_rpc_handlers([grpc.method_handlers_generic_handler(
        "ducktape.agentplane.runner.v1.Runner", {
            "Attach": grpc.stream_stream_rpc_method_handler(
                peer.attach, request_deserializer=runner_pb2.ClientMessage.FromString,
                response_serializer=runner_pb2.ServerMessage.SerializeToString,
            ),
        },
    )])
    peer.port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield peer
    finally:
        await server.stop(0)


@pytest.fixture
async def remote(cluster: Cluster, peer: Peer, tmp_path: Path) -> AsyncIterator[SandboxServiceClient]:
    cluster.fake.tokens[TOKEN] = TokenVerdict(
        username=f"system:serviceaccount:{OWNER.namespace}:{OWNER.name}",
        pod_name="test-caller", pod_uid="test-caller-uid", audiences=(AUDIENCE,),
    )
    resources = Resources(
        principals=WorkloadPrincipalResolver(
            authentication=k8s_client.AuthenticationV1Api(cluster.api), audience=AUDIENCE,
            allowed_service_account_namespaces={SANDBOX_NAMESPACE},
        ),
        destinations=DestinationResolver(cluster.inventory, k8s_client.CoreV1Api(cluster.api), peer.port),
        follow_lease_s=0.5, admission_timeout_s=1,
    )
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN)
    async with service(resources) as target:
        client = SandboxServiceClient(target, namespace=SANDBOX_NAMESPACE, token_file=token_file)
        try:
            yield client
        finally:
            await client.close()


def admission(command: command_pb2.Command, cursor: int) -> event_log_pb2.EventEntry:
    return event_log_pb2.EventEntry(
        cursor=cursor, origin=event_log_pb2.EventOrigin(source_id="test-journal", sequence=cursor),
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


async def test_follow_reconnect_rechecks_token_and_preserves_cursor(remote: SandboxServiceClient, peer: Peer) -> None:
    async with asyncio.timeout(8):
        runner = remote.runner(DESTINATION)
        attachment = await runner.attach("session", after_cursor=11)
        connection = await peer.attachments.get()
        assert connection.opened.follow.after_cursor == 11
        assert attachment.attached.session_id == "session"
        receipt = admission(command_pb2.Command(command_id="recorded"), 12)
        connection.responses.put_nowait(runner_pb2.ServerMessage(event_entry=receipt))
        assert await attachment.next_entry() == receipt
        with pytest.raises(FollowLeaseExpired):
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


@pytest.mark.parametrize("ending", [None, grpc.StatusCode.UNAVAILABLE])
async def test_native_eof_is_distinct_from_backend_failure(
    remote: SandboxServiceClient, peer: Peer, ending: grpc.StatusCode | None,
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


@pytest.mark.parametrize("metadata", [(), (("authorization", "Bearer invalid"),), (
    ("authorization", f"Bearer {TOKEN}"), ("authorization", f"Bearer {TOKEN}"),
)])
async def test_missing_invalid_or_duplicate_bearer_is_rejected(
    remote: SandboxServiceClient, peer: Peer, metadata: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as rejected:
        await remote.stub.InspectSession(
            protocol_pb2.SessionRequest(destination=wire.session_proto(DESTINATION, "session")),
            metadata=metadata,
        )
    assert rejected.value.code() == grpc.StatusCode.UNAUTHENTICATED
    assert peer.attachments.empty()


@pytest.mark.parametrize("change,code", [
    ({"owner": ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="other")}, grpc.StatusCode.PERMISSION_DENIED),
    ({"sandbox_uid": uuid4()}, grpc.StatusCode.NOT_FOUND),
])
async def test_destination_authority_and_incarnation(
    remote: SandboxServiceClient, peer: Peer, change: dict[str, object], code: grpc.StatusCode,
) -> None:
    with pytest.raises(ServiceError) as rejected:
        await remote.runner(DESTINATION.model_copy(update=change)).attach("session")
    assert rejected.value.code == code
    assert peer.attachments.empty()


async def test_management_requires_explicit_authority(remote: SandboxServiceClient, peer: Peer) -> None:
    with pytest.raises(ServiceError) as rejected:
        await remote.runner(DESTINATION).open("session", {})
    assert rejected.value.code == grpc.StatusCode.PERMISSION_DENIED
    with pytest.raises(ServiceError) as rejected:
        await remote.unary(remote.stub.ListSandboxes, Empty())
    assert rejected.value.code == grpc.StatusCode.PERMISSION_DENIED
    assert peer.attachments.empty()


async def test_wire_preserves_inventory_and_explicit_empty_overrides(cluster: Cluster) -> None:
    view = await cluster.inventory.get(SANDBOX)
    assert wire.sandbox_view(wire.sandbox_proto(view)) == view
    request = wire.open_proto(wire.session_proto(DESTINATION, "session"), {
        "model": "test-model", "instructions": "", "reasoningEffort": "",
    }, "")
    assert wire.launch_overrides(request) == {"model": "test-model", "instructions": "", "reasoningEffort": ""}
    assert request.HasField("setup_script")
    assert request.setup_script == ""
    request.override_mask.paths.append("unknown")
    with pytest.raises(ValueError):
        wire.launch_overrides(request)
    request.override_mask.paths[:] = ["model"]
    request.spec.cwd = "/unselected"
    with pytest.raises(ValueError):
        wire.launch_overrides(request)


if __name__ == "__main__":
    pytest_bazel.main()
