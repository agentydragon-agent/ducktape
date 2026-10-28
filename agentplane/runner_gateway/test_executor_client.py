"""The public executor client preserves WebSocket message boundaries and opcodes."""

from pathlib import Path
from typing import override

import grpc
import pytest_bazel

from agentplane.proto.sandboxes_pb2 import SandboxDestination, ServiceAccount
from agentplane.runner_gateway import executor_gateway_pb2, executor_gateway_pb2_grpc
from agentplane.runner_gateway.executor_client import connect

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep //agentplane/runner_gateway:executor_gateway_pb2
# gazelle:include_dep //agentplane/runner_gateway:executor_gateway_pb2_grpc


class EchoExecutor(executor_gateway_pb2_grpc.ExecutorGatewayServicer):
    def __init__(self) -> None:
        self.authorization: tuple[str, ...] = ()
        self.open: executor_gateway_pb2.ExecutorOpen | None = None

    @override
    async def Connect(self, request_iterator, context):
        self.authorization = tuple(value for key, value in context.invocation_metadata() if key == "authorization")
        first = await anext(request_iterator)
        self.open = first.open
        yield executor_gateway_pb2.ExecutorFrame(ready=executor_gateway_pb2.ExecutorReady(accepted=True))
        message = await anext(request_iterator)
        yield executor_gateway_pb2.ExecutorFrame(
            message=executor_gateway_pb2.ExecutorMessage(
                opcode=executor_gateway_pb2.ExecutorMessage.OPCODE_BINARY, payload=message.message.payload
            )
        )
        yield executor_gateway_pb2.ExecutorFrame(close=executor_gateway_pb2.ExecutorClose(code=1000, reason="done"))


async def test_executor_client_sends_identity_and_preserves_messages(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("test-executor-token\n")
    service = EchoExecutor()
    server = grpc.aio.server()
    executor_gateway_pb2_grpc.add_ExecutorGatewayServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    destination = SandboxDestination(
        owner=ServiceAccount(namespace="agentplane", name="sampler"), sandbox="sandbox-a", sandbox_uid="sandbox-uid"
    )
    try:
        async with connect(channel, token_file, destination, "pod-uid", "session-1") as socket:
            await socket.send_json({"id": 17, "method": "initialize", "params": {}})
            reply = await socket.receive()
            assert reply.type.name == "BINARY"
            assert reply.data == b'{"id":17,"method":"initialize","params":{}}'
            close = await socket.receive()
            assert close.type.name == "CLOSE"
            assert close.data == 1000
            assert close.extra == "done"
    finally:
        await channel.close()
        await server.stop(grace=0)

    assert service.authorization == ("Bearer test-executor-token",)
    assert service.open is not None
    assert service.open.destination == destination
    assert service.open.expected_incarnation_uid == "pod-uid"
    assert service.open.session_id == "session-1"


if __name__ == "__main__":
    pytest_bazel.main()
