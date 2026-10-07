"""Start the production gRPC boundary on a loopback ephemeral port."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import grpc

from agentplane.sandbox_service.client import SandboxServiceClient
from agentplane.sandbox_service.grpc_api import Resources, add_service

# gazelle:include_dep @pypi//grpcio

# Wait budgets for a `Resources` under test. `Resources` takes them from config and has no defaults of
# its own, so a test states what it waits with rather than inheriting a deployment's number. These are
# the values these helpers ran under before the waits were settings at all -- the old single
# `admission_timeout_s` was 15 -- so nothing here changes behaviour. A test that exercises one of the
# budgets overrides the one it cares about.
RESOURCE_WAIT_BUDGETS: dict[str, float] = {
    "request_timeout_s": 15,
    "command_admission_timeout_s": 15,
    "stream_write_timeout_s": 15,
}


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


@asynccontextmanager
async def service_client(resources: Resources, token_file: Path) -> AsyncIterator[SandboxServiceClient]:
    async with service(resources) as target:
        client = SandboxServiceClient(
            target, namespace=resources.destinations.inventory.namespace, token_file=token_file
        )
        try:
            yield client
        finally:
            await client.close()
