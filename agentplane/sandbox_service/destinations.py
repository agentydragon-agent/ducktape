"""Resolve an explicit, authorized Sandbox incarnation to its current controller-owned runner Pod."""

from dataclasses import dataclass
from ipaddress import ip_address
from uuid import UUID

from kubernetes_asyncio import client as k8s_client
from pydantic import BaseModel, ConfigDict, Field

from agentplane.sandbox_service.inventory import ProvisioningState, SandboxInventory, SandboxNotFoundError
from agentplane.sandbox_service.kubernetes_grants import DnsName
from agentplane.sandbox_service.session_config import SandboxBinding
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.principal import WorkloadPrincipal
from util.agent_sandbox import SANDBOX_API


class SandboxDestination(BaseModel):
    """A caller's requested resource, never proof of authority. No app Thread or supplied URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: ServiceAccountRef
    sandbox: DnsName
    sandbox_uid: UUID


class SessionDestination(SandboxDestination):
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class DestinationDeniedError(Exception):
    """The authenticated account is not allowed to address this owner."""


class DestinationUnavailableError(Exception):
    """The destination has no verified, currently reachable runner Pod. Not permanent removal."""


@dataclass(frozen=True)
class RunnerEndpoint:
    target: str
    pod_uid: str
    binding: SandboxBinding | None


@dataclass(frozen=True)
class DestinationResolver:
    inventory: SandboxInventory
    core: k8s_client.CoreV1Api
    runner_port: int
    trusted_accounts: frozenset[ServiceAccountRef] = frozenset()

    async def resolve(self, principal: WorkloadPrincipal, destination: SandboxDestination) -> RunnerEndpoint:
        # A trusted service names the resource owner explicitly. A forwarded header or request body
        # cannot make an ordinary caller a trusted service or grant cross-account access.
        if principal.account != destination.owner and principal.account not in self.trusted_accounts:
            raise DestinationDeniedError
        if destination.owner.namespace != self.inventory.namespace:
            raise DestinationDeniedError
        view = await self.inventory.get(destination.sandbox)
        if view.uid != destination.sandbox_uid or view.service_account != destination.owner:
            raise SandboxNotFoundError(destination.sandbox)
        if view.deleting or view.state is not ProvisioningState.RUNNING:
            raise DestinationUnavailableError
        try:
            pod = await self.core.read_namespaced_pod(destination.sandbox, self.inventory.namespace)
        except k8s_client.ApiException as error:
            if error.status == 404:
                raise DestinationUnavailableError from error
            raise
        metadata, spec, status = pod.metadata, pod.spec, pod.status
        if (
            metadata is None
            or metadata.name != destination.sandbox
            or metadata.namespace != self.inventory.namespace
            or not metadata.uid
            or metadata.deletion_timestamp is not None
            or spec is None
            or (spec.service_account_name or "default") != destination.owner.name
            or status is None
            or status.phase != "Running"
            or not status.pod_ip
            or not any(c.type == "Ready" and c.status == "True" for c in status.conditions or [])
        ):
            raise DestinationUnavailableError
        controllers = [ref for ref in metadata.owner_references or [] if ref.controller]
        if len(controllers) != 1:
            raise DestinationUnavailableError
        owner = controllers[0]
        if (
            owner.api_version != SANDBOX_API.api_version
            or owner.kind != "Sandbox"
            or owner.name != destination.sandbox
            or owner.uid != str(destination.sandbox_uid)
        ):
            raise DestinationUnavailableError
        try:
            address = ip_address(status.pod_ip)
        except ValueError as error:
            raise DestinationUnavailableError from error
        host = f"[{address}]" if address.version == 6 else str(address)
        return RunnerEndpoint(target=f"{host}:{self.runner_port}", pod_uid=metadata.uid, binding=view.binding)
