"""Start the production gRPC boundary on a loopback ephemeral port."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc

from agentplane.sandbox_service.grpc_api import Resources, add_service

# gazelle:include_dep @pypi//grpcio


@asynccontextmanager
async def service(resources: Resources) -> AsyncIterator[str]:
    server = grpc.aio.server()
    add_service(resources, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(0)
