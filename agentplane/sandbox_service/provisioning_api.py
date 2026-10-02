"""Namespace administration by explicitly trusted control-plane accounts, with UID-pinned mutations."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from agentplane.sandbox_service.destinations import DestinationDeniedError, SandboxDestination
from agentplane.sandbox_service.inventory import NewSandbox, SandboxNotFoundError, SandboxView
from agentplane.sandbox_service.kubernetes_grants import KubernetesGrantView, grant_views
from agentplane.sandbox_service.provisioning import Provisioning
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: SandboxDestination


def provisioning_router(
    provisioning: Provisioning,
    authenticate: WorkloadPrincipalAuthenticator,
    administrators: frozenset[ServiceAccountRef],
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["provisioning"])

    async def authorize(request: Request) -> None:
        if (await authenticate(request)).account not in administrators:
            raise DestinationDeniedError

    async def check_destination(request: Request, body: SandboxRequest) -> SandboxView:
        await authorize(request)
        view = await provisioning.inventory.get(body.destination.sandbox)
        if view.uid != body.destination.sandbox_uid or view.service_account != body.destination.owner:
            raise SandboxNotFoundError(body.destination.sandbox)
        return view

    @router.get("/sandboxes")
    async def list_sandboxes(request: Request) -> list[SandboxView]:
        await authorize(request)
        return await provisioning.inventory.list_sandboxes()

    @router.get("/sandbox-templates")
    async def templates(request: Request) -> list[str]:
        await authorize(request)
        return await provisioning.inventory.list_templates()

    @router.get("/kubernetes-grants")
    async def grants(request: Request) -> list[KubernetesGrantView]:
        await authorize(request)
        return grant_views(provisioning.grants)

    @router.post("/sandboxes", status_code=201)
    async def create(request: Request, body: NewSandbox) -> SandboxView:
        await authorize(request)
        return await provisioning.create(body)

    @router.get("/sandboxes/{name}")
    async def get(request: Request, name: str) -> SandboxView:
        await authorize(request)
        return await provisioning.inventory.get(name)

    @router.post("/sandboxes/suspend", status_code=204)
    async def suspend(request: Request, body: SandboxRequest) -> Response:
        view = await check_destination(request, body)
        await provisioning.inventory.suspend(view.name, uid=view.uid)
        return Response(status_code=204)

    @router.post("/sandboxes/resume", status_code=204)
    async def resume(request: Request, body: SandboxRequest) -> Response:
        view = await check_destination(request, body)
        if await provisioning.inventory.pending_grants(view.name) is not None:
            raise HTTPException(409, "Sandbox provisioning is incomplete")
        await provisioning.inventory.resume(view.name, uid=view.uid)
        return Response(status_code=204)

    @router.post("/sandboxes/delete", status_code=204)
    async def delete(request: Request, body: SandboxRequest) -> Response:
        view = await check_destination(request, body)
        await provisioning.inventory.delete(view.name, uid=view.uid)
        return Response(status_code=204)

    return router
