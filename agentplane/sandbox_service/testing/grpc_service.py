"""Start the production gRPC boundary on a loopback ephemeral port."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc

from agentplane.sandbox_service import protocol_pb2_grpc
from agentplane.sandbox_service.grpc_api import Resources, SandboxService

# gazelle:include_dep @pypi//grpcio


@asynccontextmanager
async def service(resources: Resources) -> AsyncIterator[str]:
    server = grpc.aio.server()
    protocol_pb2_grpc.add_SandboxServiceServicer_to_server(SandboxService(resources), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(0)
