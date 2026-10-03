"""Workload-authenticated HTTP surface; no implicit current session and no destructive reads."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from agentplane.notification_service.models import (
    Acknowledge,
    InboxPage,
    InboxView,
    Subscribe,
    SubscriptionUpdate,
    SubscriptionView,
)
from agentplane.notification_service.service import DestinationRejectedError, Service
from agentplane.notification_service.store import ConflictError, NotFoundError, QuotaError
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator
from agentplane.workload_auth.principal import WorkloadPrincipal, WorkloadPrincipalResolver


def create_app(service: Service, principals: WorkloadPrincipalResolver) -> FastAPI:
    authenticate = WorkloadPrincipalAuthenticator(principals)
    workers: list[asyncio.Task[None]] = []

    async def principal(request: Request) -> WorkloadPrincipal:
        return await authenticate(request)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        workers.extend(asyncio.create_task(service.run(), name=f"notifications-{i}") for i in range(4))
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    app = FastAPI(title="Agentplane notifications", lifespan=lifespan)

    @app.exception_handler(NotFoundError)
    @app.exception_handler(DestinationRejectedError)
    async def missing(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "resource not found or not owned by this account"}, status_code=404)

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, error: ConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(QuotaError)
    async def quota(request: Request, error: QuotaError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=429)

    @app.exception_handler(ConnectionError)
    @app.exception_handler(TimeoutError)
    @app.exception_handler(httpx.HTTPError)
    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "backend temporarily unavailable"}, status_code=503)

    @app.get("/readyz")
    async def ready() -> dict[str, str]:
        if not workers or any(worker.done() for worker in workers):
            raise HTTPException(503, "notification workers unavailable")
        async with service.store.sessions() as session:
            await session.execute(select(1))
        return {"status": "ready"}

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/v1/providers")
    async def providers(caller: Annotated[WorkloadPrincipal, Depends(principal)]) -> dict[str, object]:
        return {
            "actions": {
                "subscription_schema": Subscribe.model_json_schema(),
                "content": "ActionEventView: sequence, state, at, actor",
            }
        }

    @app.post("/v1/subscriptions", response_model=SubscriptionView)
    async def subscribe(body: Subscribe, caller: Annotated[WorkloadPrincipal, Depends(principal)]) -> SubscriptionView:
        try:
            return await service.subscribe(caller, body)
        except httpx.HTTPStatusError as error:
            raise HTTPException(
                403 if error.response.status_code in (401, 403, 404) else 503,
                "Action source unavailable or unauthorized",
            ) from error

    @app.get("/v1/subscriptions")
    async def subscriptions(
        caller: Annotated[WorkloadPrincipal, Depends(principal)], after_id: UUID | None = None
    ) -> list[SubscriptionView]:
        return await service.store.subscriptions(caller.account, after_id)

    @app.get("/v1/subscriptions/{subscription_id}")
    async def subscription(
        subscription_id: UUID, caller: Annotated[WorkloadPrincipal, Depends(principal)]
    ) -> SubscriptionView:
        return await service.store.subscription(caller.account, subscription_id)

    @app.patch("/v1/subscriptions/{subscription_id}")
    async def update(
        subscription_id: UUID, body: SubscriptionUpdate, caller: Annotated[WorkloadPrincipal, Depends(principal)]
    ) -> SubscriptionView:
        return await service.store.change(caller.account, subscription_id, body)

    @app.delete("/v1/subscriptions/{subscription_id}")
    async def cancel(
        subscription_id: UUID, caller: Annotated[WorkloadPrincipal, Depends(principal)]
    ) -> SubscriptionView:
        return await service.store.change(caller.account, subscription_id, None)

    @app.get("/v1/inboxes")
    async def inboxes(caller: Annotated[WorkloadPrincipal, Depends(principal)]) -> list[InboxView]:
        return await service.store.inboxes(caller.account)

    @app.get("/v1/inboxes/{inbox_id}/entries")
    async def read(
        inbox_id: UUID,
        caller: Annotated[WorkloadPrincipal, Depends(principal)],
        after_cursor: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
        limit: Annotated[int, Query(ge=1, le=128)] = 128,
    ) -> InboxPage:
        return await service.store.read(caller.account, inbox_id, after_cursor, limit)

    @app.put("/v1/inboxes/{inbox_id}/acknowledgement")
    async def acknowledge(
        inbox_id: UUID, body: Acknowledge, caller: Annotated[WorkloadPrincipal, Depends(principal)]
    ) -> InboxView:
        return await service.store.acknowledge(caller.account, inbox_id, body.through_cursor)

    @app.delete("/v1/inboxes/{inbox_id}", status_code=204)
    async def retire(inbox_id: UUID, caller: Annotated[WorkloadPrincipal, Depends(principal)]) -> Response:
        await service.store.retire(caller.account, inbox_id)
        return Response(status_code=204)

    return app
