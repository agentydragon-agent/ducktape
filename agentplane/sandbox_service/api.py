"""Authenticated access to existing runner sessions; no app, private archive, queue, or implicit wake."""

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
from agentplane.sandbox_service.command_relay import admit_running_command
from agentplane.sandbox_service.destinations import (
    DestinationDeniedError,
    DestinationResolver,
    DestinationUnavailableError,
    SessionDestination,
)
from agentplane.sandbox_service.inventory import SandboxNotFoundError
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep @pypi//grpcio


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: SessionDestination


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

    def __post_init__(self) -> None:
        if self.admission_timeout_s <= 0 or self.follow_lease_s <= 0:
            raise ValueError("timeouts must be positive")

    async def client(self, request: Request, destination: SessionDestination) -> RunnerClient:
        principal = await self.authenticate(request)
        endpoint = await self.destinations.resolve(principal, destination)
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

    @app.exception_handler(DestinationDeniedError)
    async def denied(request: Request, error: DestinationDeniedError) -> JSONResponse:
        return JSONResponse({"detail": "destination access denied"}, status_code=403)

    @app.exception_handler(SandboxNotFoundError)
    async def missing(request: Request, error: SandboxNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "sandbox incarnation not found"}, status_code=404)

    @app.exception_handler(DestinationUnavailableError)
    @app.exception_handler(grpc.RpcError)
    @app.exception_handler(k8s_client.ApiException)
    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "destination unavailable; no offline admission"}, status_code=503)

    @app.exception_handler(RunnerError)
    @app.exception_handler(StreamClosedError)
    async def refused(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "runner refused or closed the session request"}, status_code=409)

    @app.exception_handler(TimeoutError)
    async def timeout(request: Request, error: TimeoutError) -> JSONResponse:
        return JSONResponse(
            {"detail": "runner receipt timed out; reconcile with the unchanged command"}, status_code=504
        )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
