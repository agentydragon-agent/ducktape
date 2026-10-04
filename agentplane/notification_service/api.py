"""Workload-authenticated HTTP surface; no implicit current session and no destructive reads."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from agentplane.notification_service.sources.actions import SourceNotOwnedError
from agentplane.notification_service.sources.github import GitHubRetryError, GitHubUnavailableError, InvalidSignatureError
from agentplane.notification_service.models import (
    Acknowledge,
    InboxPage,
    InboxView,
    SourceView,
    Subscribe,
    SubscriptionUpdate,
    SubscriptionView,
)
from agentplane.notification_service.service import DestinationRejectedError, Service
from agentplane.notification_service.store import ConflictError, NotFoundError, QuotaError
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator
from agentplane.workload_auth.principal import WorkloadPrincipal, WorkloadPrincipalResolver


def notification_service(request: Request) -> Service:
    return cast(Service, request.app.state.notification_service)


def workload_authenticator(request: Request) -> WorkloadPrincipalAuthenticator:
    return cast(WorkloadPrincipalAuthenticator, request.app.state.workload_authenticator)


async def authenticated_caller(
    request: Request, authenticate: Annotated[WorkloadPrincipalAuthenticator, Depends(workload_authenticator)]
) -> WorkloadPrincipal:
    return await authenticate(request)


Caller = Annotated[WorkloadPrincipal, Depends(authenticated_caller)]
Notifications = Annotated[Service, Depends(notification_service)]
router = APIRouter()


@router.get("/readyz")
async def ready(request: Request, service: Notifications) -> dict[str, str]:
    workers = cast(list[asyncio.Task[None]], request.app.state.notification_workers)
    if not workers or any(worker.done() for worker in workers) or not service.store.wakeups.connected:
        raise HTTPException(503, "notification workers unavailable")
    async with service.store.sessions() as session:
        await session.execute(select(1))
    return {"status": "ready"}


@router.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/v1/sources")
async def sources(caller: Caller, service: Notifications) -> dict[str, SourceView]:
    result = {
        "actions": SourceView(
            subscription_schema=Subscribe.model_json_schema(), content="ActionEventView: sequence, state, at, actor"
        )
    }
    if service.github is not None:
        result["github"] = SourceView(
            subscription_schema=Subscribe.model_json_schema(), content="Full GitHub webhook JSON; identity in event"
        )
    return result


@router.post("/v1/webhooks/github", status_code=202)
async def github_webhook(request: Request, service: Notifications) -> dict[str, bool]:
    github = service.github
    if github is None:
        raise HTTPException(404, "GitHub provider is disabled")
    if github.ingress_slots.locked():
        raise HTTPException(503, "GitHub ingress busy", headers={"Retry-After": "5"})
    raw = bytearray()
    async with github.ingress_slots, asyncio.timeout(10):
        async for chunk in request.stream():
            if len(raw) + len(chunk) > github.settings.max_body_bytes:
                raise HTTPException(413, "GitHub payload exceeds configured limit")
            raw.extend(chunk)
        try:
            created = await github.ingest(
                service.store,
                request.headers.get("x-github-event", ""),
                UUID(request.headers.get("x-github-delivery", "")),
                request.headers.get("x-hub-signature-256", ""),
                bytes(raw),
            )
        except InvalidSignatureError as error:
            raise HTTPException(401, "invalid GitHub signature") from error
        except ValueError as error:
            raise HTTPException(400, "invalid GitHub delivery") from error
    return {"accepted": True, "duplicate": not created}


@router.post("/v1/subscriptions", response_model=SubscriptionView)
async def subscribe(body: Subscribe, caller: Caller, service: Notifications) -> SubscriptionView:
    try:
        return await service.subscribe(caller, body)
    except GitHubUnavailableError as error:
        raise HTTPException(403, str(error)) from error
    except GitHubRetryError as error:
        raise HTTPException(
            503, "GitHub temporarily unavailable", headers={"Retry-After": str(error.retry_seconds)}
        ) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            403 if error.response.status_code in (401, 403, 404) else 503, "Source unavailable or unauthorized"
        ) from error


@router.get("/v1/subscriptions")
async def subscriptions(caller: Caller, service: Notifications, after_id: UUID | None = None) -> list[SubscriptionView]:
    return await service.store.subscriptions(caller.account, after_id)


@router.get("/v1/subscriptions/{subscription_id}")
async def subscription(subscription_id: UUID, caller: Caller, service: Notifications) -> SubscriptionView:
    return await service.store.subscription(caller.account, subscription_id)


@router.patch("/v1/subscriptions/{subscription_id}")
async def update(
    subscription_id: UUID, body: SubscriptionUpdate, caller: Caller, service: Notifications
) -> SubscriptionView:
    return await service.store.change(caller.account, subscription_id, body)


@router.delete("/v1/subscriptions/{subscription_id}")
async def cancel(subscription_id: UUID, caller: Caller, service: Notifications) -> SubscriptionView:
    return await service.store.change(caller.account, subscription_id, None)


@router.get("/v1/inboxes")
async def inboxes(caller: Caller, service: Notifications) -> list[InboxView]:
    return await service.store.inboxes(caller.account)


@router.get("/v1/inboxes/{inbox_id}/entries")
async def read(
    inbox_id: UUID,
    caller: Caller,
    service: Notifications,
    after_cursor: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    limit: Annotated[int, Query(ge=1, le=128)] = 128,
) -> InboxPage:
    return await service.store.read(caller.account, inbox_id, after_cursor, limit)


@router.put("/v1/inboxes/{inbox_id}/acknowledgement")
async def acknowledge(inbox_id: UUID, body: Acknowledge, caller: Caller, service: Notifications) -> InboxView:
    return await service.store.acknowledge(caller.account, inbox_id, body.through_cursor)


@router.delete("/v1/inboxes/{inbox_id}", status_code=204)
async def retire(inbox_id: UUID, caller: Caller, service: Notifications) -> Response:
    await service.store.retire(caller.account, inbox_id)
    return Response(status_code=204)


async def missing(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse({"detail": "resource not found or not owned by this account"}, status_code=404)


async def source_not_owned(request: Request, error: SourceNotOwnedError) -> JSONResponse:
    return JSONResponse({"detail": "Source unavailable or unauthorized"}, status_code=403)


async def conflict(request: Request, error: ConflictError) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=409)


async def quota(request: Request, error: QuotaError) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=429)


async def unavailable(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse({"detail": "backend temporarily unavailable"}, status_code=503)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    service = cast(Service, app.state.notification_service)
    async with service.store.wakeups.listen():
        workers = [asyncio.create_task(service.run(), name=f"notifications-{i}") for i in range(4)]
        app.state.notification_workers = workers
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)


def create_app(service: Service, principals: WorkloadPrincipalResolver) -> FastAPI:
    app = FastAPI(
        title="Agentplane notifications",
        lifespan=_lifespan,
        exception_handlers={
            NotFoundError: missing,
            DestinationRejectedError: missing,
            SourceNotOwnedError: source_not_owned,
            ConflictError: conflict,
            QuotaError: quota,
            ConnectionError: unavailable,
            TimeoutError: unavailable,
            httpx.HTTPError: unavailable,
        },
    )
    app.state.notification_service = service
    app.state.workload_authenticator = WorkloadPrincipalAuthenticator(principals)
    app.state.notification_workers = []
    app.include_router(router)
    return app
