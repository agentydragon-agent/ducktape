"""Authenticated gRPC boundary. Runners remain the command and execution-event authority."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import grpc
from google.protobuf.empty_pb2 import Empty
from google.protobuf.json_format import ParseDict, ParseError
from kubernetes_asyncio import client as k8s_client

from agentplane.protocol import event_log_pb2
from agentplane.runner import protocol_pb2 as runner_pb2
from agentplane.runner.client import RunnerClient, RunnerError, StreamClosedError
from agentplane.sandbox_service import protocol_pb2, protocol_pb2_grpc, session_lifecycle, wire
from agentplane.sandbox_service.action_policy import UnknownPolicySetError
from agentplane.sandbox_service.egress import UnknownPolicyError
from agentplane.sandbox_service.command_relay import admit_running_command
from agentplane.sandbox_service.destinations import (
    DestinationDeniedError,
    DestinationResolver,
    DestinationUnavailableError,
    RunnerEndpoint,
    SandboxDestination,
)
from agentplane.sandbox_service.inventory import InventoryError, SandboxNotFoundError, SandboxView
from agentplane.sandbox_service.kubernetes_grants import grant_views
from agentplane.sandbox_service.provisioning import Provisioning
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.bearer import parse_bearer, sole_header
from agentplane.workload_auth.principal import (
    WorkloadPrincipal,
    WorkloadPrincipalRejectedError,
    WorkloadPrincipalResolver,
)

# gazelle:include_dep @pypi//protobuf
# gazelle:include_dep @pypi//grpcio


@dataclass(frozen=True)
class Resources:
    principals: WorkloadPrincipalResolver
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

    async def authenticate(self, context: grpc.aio.ServicerContext) -> WorkloadPrincipal:
        values = [value for key, value in context.invocation_metadata() if key == "authorization"]
        if any(not isinstance(value, str) for value in values):
            raise WorkloadPrincipalRejectedError("invalid bearer metadata")
        value = sole_header([value for value in values if isinstance(value, str)])
        token = parse_bearer(value) if value is not None else None
        if token is None:
            raise WorkloadPrincipalRejectedError("invalid bearer metadata")
        return await self.principals.resolve_workload(token)

    async def endpoint(
        self, principal: WorkloadPrincipal, destination: SandboxDestination, *, manage: bool = False
    ) -> RunnerEndpoint:
        if manage and principal.account not in self.manager_accounts:
            raise DestinationDeniedError
        return await self.destinations.resolve(principal, destination)

    def administrator(self, principal: WorkloadPrincipal) -> Provisioning:
        if principal.account not in self.manager_accounts & self.destinations.trusted_accounts:
            raise DestinationDeniedError
        if self.provisioning is None:
            raise DestinationUnavailableError
        return self.provisioning


@asynccontextmanager
async def errors(context: grpc.aio.ServicerContext) -> AsyncIterator[None]:
    """Sanitize backend failures; no Kubernetes wire responses or bearer data reach clients."""
    try:
        yield
    except WorkloadPrincipalRejectedError:
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid workload bearer")
    except DestinationDeniedError:
        await context.abort(grpc.StatusCode.PERMISSION_DENIED, "destination access denied")
    except SandboxNotFoundError:
        await context.abort(grpc.StatusCode.NOT_FOUND, "sandbox incarnation not found")
    except (ValueError, ParseError, UnknownPolicyError, UnknownPolicySetError):
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid service request or grant selection")
    except (InventoryError, RunnerError, StreamClosedError):
        await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "runner or sandbox state refused the request")
    except TimeoutError:
        await context.abort(
            grpc.StatusCode.DEADLINE_EXCEEDED,
            "service deadline or follow lease expired; mutation outcome may be uncertain",
        )
    except (DestinationUnavailableError, k8s_client.ApiException):
        await context.abort(grpc.StatusCode.UNAVAILABLE, "destination unavailable; no offline admission")
    except grpc.RpcError as error:
        if isinstance(error, grpc.aio.AioRpcError):
            if error.code() == grpc.StatusCode.INVALID_ARGUMENT:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "runner rejected invalid request")
            if error.code() in (grpc.StatusCode.FAILED_PRECONDITION, grpc.StatusCode.NOT_FOUND):
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "runner rejected session or bootstrap state")
        await context.abort(grpc.StatusCode.UNAVAILABLE, "runner unavailable; mutation outcome may be uncertain")


class SandboxService(protocol_pb2_grpc.SandboxServiceServicer):
    def __init__(self, resources: Resources) -> None:
        self.resources = resources

    @asynccontextmanager
    async def request(
        self, context: grpc.aio.ServicerContext, *, timeout_s: float | None = None
    ) -> AsyncIterator[WorkloadPrincipal]:
        async with errors(context), asyncio.timeout(timeout_s or self.resources.admission_timeout_s):
            yield await self.resources.authenticate(context)

    @asynccontextmanager
    async def runner(
        self, principal: WorkloadPrincipal, destination: SandboxDestination, *, manage: bool = False
    ) -> AsyncIterator[tuple[RunnerClient, RunnerEndpoint]]:
        endpoint = await self.resources.endpoint(principal, destination, manage=manage)
        # TODO: runner RPC authentication/TLS. V1 relies on the deployment network boundary.
        client = RunnerClient(endpoint.target)
        try:
            yield client, endpoint
        finally:
            await client.close()

    async def ListSandboxes(self, request: Empty, context: grpc.aio.ServicerContext) -> protocol_pb2.ListSandboxesResponse:  # noqa: N802
        async with self.request(context) as principal:
            inventory = self.resources.administrator(principal).inventory
            return protocol_pb2.ListSandboxesResponse(sandboxes=[wire.sandbox_proto(v) for v in await inventory.list_sandboxes()])

    async def GetSandbox(self, request: protocol_pb2.GetSandboxRequest, context: grpc.aio.ServicerContext) -> protocol_pb2.Sandbox:  # noqa: N802
        async with self.request(context) as principal:
            inventory = self.resources.administrator(principal).inventory
            if not request.name:
                raise ValueError("name is required")
            return wire.sandbox_proto(await inventory.get(request.name))

    async def CreateSandbox(self, request: protocol_pb2.CreateSandboxRequest, context: grpc.aio.ServicerContext) -> protocol_pb2.Sandbox:  # noqa: N802
        async with self.request(context, timeout_s=self.resources.lifecycle_timeout_s) as principal:
            provisioning = self.resources.administrator(principal)
            return wire.sandbox_proto(await provisioning.create(wire.new_sandbox(request)))

    async def checked_sandbox(self, principal: WorkloadPrincipal, request: protocol_pb2.SandboxRequest) -> tuple[Provisioning, SandboxView]:
        provisioning = self.resources.administrator(principal)
        destination = wire.sandbox_destination(request.destination)
        view = await provisioning.inventory.get(destination.sandbox)
        if view.uid != destination.sandbox_uid or view.service_account != destination.owner:
            raise SandboxNotFoundError(destination.sandbox)
        return provisioning, view

    async def SuspendSandbox(self, request: protocol_pb2.SandboxRequest, context: grpc.aio.ServicerContext) -> Empty:  # noqa: N802
        async with self.request(context) as principal:
            provisioning, view = await self.checked_sandbox(principal, request)
            await provisioning.inventory.suspend(view.name, uid=view.uid)
            return Empty()

    async def ResumeSandbox(self, request: protocol_pb2.SandboxRequest, context: grpc.aio.ServicerContext) -> Empty:  # noqa: N802
        async with self.request(context) as principal:
            provisioning, view = await self.checked_sandbox(principal, request)
            if await provisioning.inventory.pending_grants(view.name) is not None:
                raise InventoryError("Sandbox provisioning is incomplete")
            await provisioning.inventory.resume(view.name, uid=view.uid)
            return Empty()

    async def DeleteSandbox(self, request: protocol_pb2.SandboxRequest, context: grpc.aio.ServicerContext) -> Empty:  # noqa: N802
        async with self.request(context) as principal:
            provisioning, view = await self.checked_sandbox(principal, request)
            await provisioning.inventory.delete(view.name, uid=view.uid)
            return Empty()

    async def ListTemplates(self, request: Empty, context: grpc.aio.ServicerContext) -> protocol_pb2.ListTemplatesResponse:  # noqa: N802
        async with self.request(context) as principal:
            inventory = self.resources.administrator(principal).inventory
            return protocol_pb2.ListTemplatesResponse(templates=await inventory.list_templates())

    async def ListKubernetesGrants(self, request: Empty, context: grpc.aio.ServicerContext) -> protocol_pb2.ListKubernetesGrantsResponse:  # noqa: N802
        async with self.request(context) as principal:
            provisioning = self.resources.administrator(principal)
            return protocol_pb2.ListKubernetesGrantsResponse(grants=[
                ParseDict(view.model_dump(mode="json", exclude_none=True), protocol_pb2.KubernetesGrantView())
                for view in grant_views(provisioning.grants)
            ])

    async def ListSessions(self, request: protocol_pb2.SandboxRequest, context: grpc.aio.ServicerContext) -> runner_pb2.ListSessionsResponse:  # noqa: N802
        async with self.request(context) as principal:
            async with self.runner(principal, wire.sandbox_destination(request.destination)) as (client, _):
                return runner_pb2.ListSessionsResponse(sessions=await client.list_sessions())

    async def InitializeSandbox(self, request: protocol_pb2.SandboxRequest, context: grpc.aio.ServicerContext) -> runner_pb2.InitializeResult:  # noqa: N802
        async with self.request(context, timeout_s=self.resources.lifecycle_timeout_s) as principal:
            async with self.runner(principal, wire.sandbox_destination(request.destination), manage=True) as (client, endpoint):
                return await session_lifecycle.initialize(client, endpoint.binding)

    async def OpenSession(self, request: protocol_pb2.OpenSessionRequest, context: grpc.aio.ServicerContext) -> runner_pb2.Attached:  # noqa: N802
        async with self.request(context, timeout_s=self.resources.lifecycle_timeout_s) as principal:
            destination = wire.session_destination(request.destination)
            async with self.runner(principal, destination, manage=True) as (client, endpoint):
                assert self.resources.platform_instructions is not None
                if len(request.setup_script) > 65_536:
                    raise ValueError("setup script is too long")
                spec = session_lifecycle.launch_spec(
                    destination, wire.launch_overrides(request), binding=endpoint.binding,
                    platform_instructions=self.resources.platform_instructions,
                )
                return await session_lifecycle.open_session(
                    client, destination, spec, binding=endpoint.binding,
                    setup_script=request.setup_script if request.HasField("setup_script") else None,
                )

    async def ResumeSession(self, request: protocol_pb2.SessionRequest, context: grpc.aio.ServicerContext) -> runner_pb2.Attached:  # noqa: N802
        async with self.request(context, timeout_s=self.resources.lifecycle_timeout_s) as principal:
            destination = wire.session_destination(request.destination)
            async with self.runner(principal, destination, manage=True) as (client, _):
                return await session_lifecycle.resume_session(client, destination.session_id)

    async def InspectSession(self, request: protocol_pb2.SessionRequest, context: grpc.aio.ServicerContext) -> runner_pb2.Attached:  # noqa: N802
        async with self.request(context) as principal:
            destination = wire.session_destination(request.destination)
            async with self.runner(principal, destination) as (client, _):
                attachment = await client.attach(destination.session_id)
                try:
                    return attachment.attached
                finally:
                    attachment.cancel()

    async def SubmitCommand(self, request: protocol_pb2.SubmitCommandRequest, context: grpc.aio.ServicerContext) -> event_log_pb2.EventEntry:  # noqa: N802
        async with self.request(context) as principal:
            destination = wire.session_destination(request.destination)
            if not request.command.command_id or request.command.WhichOneof("operation") is None:
                raise ValueError("command ID and operation are required")
            async with self.runner(principal, destination) as (client, _):
                return await admit_running_command(
                    client, destination.session_id, request.command,
                    after_cursor=request.follow.after_cursor, timeout_s=self.resources.admission_timeout_s,
                )

    async def FollowSession(self, request: protocol_pb2.FollowSessionRequest, context: grpc.aio.ServicerContext) -> None:  # noqa: N802
        # Explicit writes keep flow-control stalls inside our deadline and finally blocks.
        async with errors(context):
            async with asyncio.timeout(self.resources.admission_timeout_s):
                principal = await self.resources.authenticate(context)
                destination = wire.session_destination(request.destination)
                endpoint = await self.resources.endpoint(principal, destination)
            client = RunnerClient(endpoint.target)
            try:
                async with asyncio.timeout(self.resources.admission_timeout_s):
                    attachment = await client.attach(destination.session_id, after_cursor=request.follow.after_cursor)
                try:
                    async with asyncio.timeout(self.resources.follow_lease_s):
                        await context.write(protocol_pb2.FollowSessionResponse(attached=attachment.attached))
                        while True:
                            try:
                                entry = await attachment.next_entry()
                            except StreamClosedError:
                                await context.write(protocol_pb2.FollowSessionResponse(ended=Empty()))
                                return
                            await context.write(protocol_pb2.FollowSessionResponse(entry=entry))
                finally:
                    attachment.cancel()
            finally:
                await client.close()
