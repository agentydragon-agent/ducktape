"""Authenticated runner session access and explicit management; no app, private archive, queue, or implicit wake."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import grpc
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from kubernetes_asyncio import client as k8s_client
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import Receive, Scope, Send

from agentplane.protocol import command_pb2
from agentplane.runner.client import Attachment, RunnerClient, RunnerError, StreamClosedError
from agentplane.sandbox_service import session_lifecycle
from agentplane.sandbox_service.command_relay import admit_running_command
from agentplane.sandbox_service.destinations import (
    DestinationDeniedError,
    DestinationResolver,
    DestinationUnavailableError,
    RunnerEndpoint,
    SandboxDestination,
    SessionDestination,
)
from agentplane.sandbox_service.inventory import InventoryError, SandboxNotFoundError
from agentplane.sandbox_service.action_policy import UnknownPolicySetError
from agentplane.sandbox_service.egress import UnknownPolicyError
from agentplane.sandbox_service.kubernetes_grants import DuplicateKubernetesGrantError, UnknownKubernetesGrantError
from agentplane.sandbox_service.provisioning import Provisioning
from agentplane.sandbox_service.provisioning_api import provisioning_router
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep @pypi//grpcio


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: SandboxDestination


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: SessionDestination


class OpenRequest(SessionRequest):
    spec: dict[str, object] = Field(default_factory=dict)
    setup_script: str | None = Field(default=None, max_length=65_536)


class FollowRequest(SessionRequest):
    after_cursor: int = Field(default=0, ge=0, le=2**64 - 1)


class CommandRequest(FollowRequest):
    command: dict[str, object]


@dataclass(frozen=True)
class SessionResources:
    authenticate: WorkloadPrincipalAuthenticator
    destinations: DestinationResolver
    admission_timeout_s: float = 15
    follow_lease_s: float = 30
    manager_accounts: frozenset[ServiceAccountRef] = frozenset()
    platform_instructions: str | None = None
    lifecycle_timeout_s: float = 300
    provisioning: Provisioning | None = None

    def __post_init__(self) -> None:
        if min(self.admission_timeout_s, self.follow_lease_s, self.lifecycle_timeout_s) <= 0:
            raise ValueError("timeouts must be positive")
        if self.manager_accounts and self.platform_instructions is None:
            raise ValueError("session management requires configured platform instructions")

    async def endpoint(
        self, request: Request, destination: SandboxDestination, *, manage: bool = False
    ) -> RunnerEndpoint:
        principal = await self.authenticate(request)
        if manage and principal.account not in self.manager_accounts:
            raise DestinationDeniedError
        return await self.destinations.resolve(principal, destination)

    async def client(self, request: Request, destination: SandboxDestination, *, manage: bool = False) -> RunnerClient:
        endpoint = await self.endpoint(request, destination, manage=manage)
        # TODO: authenticate/TLS-protect the runner RPC. V1 relies on network isolation;
        # Kubernetes association checks are not cryptographic authentication of the peer.
        return RunnerClient(endpoint.target)


class SessionStream(StreamingResponse):
    """Close the attachment even if ASGI disconnects before starting the response iterator."""

    def __init__(self, client: RunnerClient, attachment: Attachment, *, lease_s: float) -> None:
        self._client = client
        self._attachment = attachment
        self._lease_s = lease_s
        super().__init__(self._entries(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    async def _entries(self) -> AsyncIterator[str]:
        try:
            # Bound authorization staleness, resource use and slow consumers. Reconnect with the
            # last consumed runner cursor; every new request reviews identity and destination again.
            async with asyncio.timeout(self._lease_s):
                while True:
                    entry = await self._attachment.next_entry()
                    yield f"event: entry\ndata: {json.dumps(MessageToDict(entry))}\n\n"
        except TimeoutError, StreamClosedError:
            return
        except RunnerError, grpc.RpcError:
            # A transport envelope, deliberately not a synthetic runner Event or success receipt.
            yield 'event: unavailable\ndata: {"detail":"runner follow ended without a complete receipt"}\n\n'

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            # The iterator timeout alone cannot bound a blocked ASGI send after yielding an entry.
            async with asyncio.timeout(self._lease_s + 5):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            pass
        finally:
            self._attachment.cancel()
            await self._client.close()


def create_app(resources: SessionResources) -> FastAPI:
    app = FastAPI(title="Agentplane Sandbox Service")

    if resources.provisioning is not None:
        app.include_router(provisioning_router(
            resources.provisioning, resources.authenticate,
            resources.manager_accounts & resources.destinations.trusted_accounts,
        ))

    @app.exception_handler(InventoryError)
    async def inventory_error(request: Request, error: InventoryError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(UnknownPolicyError)
    @app.exception_handler(UnknownPolicySetError)
    @app.exception_handler(UnknownKubernetesGrantError)
    @app.exception_handler(DuplicateKubernetesGrantError)
    async def invalid_selection(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(DestinationDeniedError)
    async def denied(request: Request, error: DestinationDeniedError) -> JSONResponse:
        return JSONResponse({"detail": "destination access denied"}, status_code=403)

    @app.exception_handler(SandboxNotFoundError)
    async def missing(request: Request, error: SandboxNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "sandbox incarnation not found"}, status_code=404)

    @app.exception_handler(DestinationUnavailableError)
    @app.exception_handler(k8s_client.ApiException)
    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "destination unavailable; no offline admission"}, status_code=503)

    @app.exception_handler(grpc.RpcError)
    async def rpc_failure(request: Request, error: grpc.RpcError) -> JSONResponse:
        if isinstance(error, grpc.aio.AioRpcError):
            if error.code() == grpc.StatusCode.INVALID_ARGUMENT:
                return JSONResponse({"detail": "runner rejected invalid request"}, status_code=422)
            if error.code() in (grpc.StatusCode.FAILED_PRECONDITION, grpc.StatusCode.NOT_FOUND):
                return JSONResponse({"detail": "runner rejected session or bootstrap state"}, status_code=409)
        return JSONResponse({"detail": "destination unavailable; outcome uncertain"}, status_code=503)

    @app.exception_handler(RunnerError)
    @app.exception_handler(StreamClosedError)
    async def refused(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "runner refused or closed the session request"}, status_code=409)

    @app.exception_handler(TimeoutError)
    async def timeout(request: Request, error: TimeoutError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "runner request timed out; outcome uncertain, reconcile using unchanged identifiers and payload"
            },
            status_code=504,
        )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/sessions/list")
    async def list_sessions(body: SandboxRequest, request: Request) -> dict[str, object]:
        client = await resources.client(request, body.destination)
        try:
            async with asyncio.timeout(resources.admission_timeout_s):
                return {"sessions": [MessageToDict(row) for row in await client.list_sessions()]}
        finally:
            await client.close()

    @app.post("/v1/sandboxes/initialize")
    async def initialize(body: SandboxRequest, request: Request) -> dict[str, object]:
        endpoint = await resources.endpoint(request, body.destination, manage=True)
        client = RunnerClient(endpoint.target)
        try:
            async with asyncio.timeout(resources.lifecycle_timeout_s):
                return MessageToDict(await session_lifecycle.initialize(client, endpoint.binding))
        finally:
            await client.close()

    @app.post("/v1/sessions/open")
    async def open_session(body: OpenRequest, request: Request) -> dict[str, object]:
        endpoint = await resources.endpoint(request, body.destination, manage=True)
        assert resources.platform_instructions is not None
        try:
            spec = session_lifecycle.launch_spec(
                body.destination,
                body.spec,
                binding=endpoint.binding,
                platform_instructions=resources.platform_instructions,
            )
        except (ParseError, ValueError) as error:
            raise HTTPException(422, "invalid runner SessionSpec") from error
        client = RunnerClient(endpoint.target)
        try:
            async with asyncio.timeout(resources.lifecycle_timeout_s):
                return MessageToDict(
                    await session_lifecycle.open_session(
                        client, body.destination, spec, binding=endpoint.binding, setup_script=body.setup_script
                    )
                )
        finally:
            await client.close()

    @app.post("/v1/sessions/resume")
    async def resume_session(body: SessionRequest, request: Request) -> dict[str, object]:
        client = await resources.client(request, body.destination, manage=True)
        try:
            async with asyncio.timeout(resources.lifecycle_timeout_s):
                return MessageToDict(await session_lifecycle.resume_session(client, body.destination.session_id))
        finally:
            await client.close()

    @app.post("/v1/sessions/inspect")
    async def inspect(body: SessionRequest, request: Request) -> dict[str, object]:
        client = await resources.client(request, body.destination)
        try:
            attachment = await client.attach(body.destination.session_id)
            try:
                return MessageToDict(attachment.attached)
            finally:
                attachment.cancel()
        finally:
            await client.close()

    @app.post("/v1/sessions/commands")
    async def command(body: CommandRequest, request: Request) -> dict[str, object]:
        client = await resources.client(request, body.destination)
        try:
            try:
                parsed = ParseDict(body.command, command_pb2.Command())
            except ParseError as error:
                raise HTTPException(422, "invalid runner Command") from error
            if not parsed.command_id or parsed.WhichOneof("operation") is None:
                raise HTTPException(422, "command ID and operation are required")
            receipt = await admit_running_command(
                client,
                body.destination.session_id,
                parsed,
                after_cursor=body.after_cursor,
                timeout_s=resources.admission_timeout_s,
            )
            return MessageToDict(receipt)
        finally:
            await client.close()

    @app.post("/v1/sessions/follow")
    async def follow(body: FollowRequest, request: Request) -> StreamingResponse:
        client = await resources.client(request, body.destination)
        try:
            attachment = await client.attach(body.destination.session_id, after_cursor=body.after_cursor)
        except BaseException:
            await client.close()
            raise
        return SessionStream(client, attachment, lease_s=resources.follow_lease_s)

    return app
