"""Public Sandbox Service request/response models and client-visible domain errors."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agentplane.sandbox_service.kubernetes_grants import DnsName, ResolvedGrant
from agentplane.sandbox_service.session_config import SandboxBinding, ThreadDefaults
from agentplane.subjects import ServiceAccountRef

Slug = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", min_length=1, max_length=57)
]


class OperatingMode(StrEnum):
    RUNNING = "Running"
    SUSPENDED = "Suspended"


class ProvisioningState(StrEnum):
    WAITING_FOR_GRANTS = "waiting_for_grants"
    WAITING_FOR_POD = "waiting_for_pod"
    WAITING_FOR_POD_READY = "waiting_for_pod_ready"
    RUNNING = "running"
    SUSPENDED = "suspended"


class InventoryError(Exception):
    """Base of the errors the API maps to status codes."""


class SandboxNotFoundError(InventoryError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no Agentplane sandbox {name=}")
        self.name = name


class SandboxRunningError(InventoryError):
    """Deletion is refused while the sandbox runs; the message is what the UI shows the operator."""

    def __init__(self, name: str) -> None:
        super().__init__(f"sandbox {name} is running; suspend it before deleting it")


class NewSandbox(BaseModel):
    """The concrete sandbox choices a caller makes after optionally applying a form preset."""

    model_config = ConfigDict(extra="forbid")

    slug: Slug = Field(description="Human-chosen name stem; a random suffix makes the Sandbox name unique.")
    template: str = Field(min_length=1, description="SandboxTemplate whose Pod and volume shape this Sandbox copies.")
    policies: list[str] = Field(default_factory=list, description="EgressPolicy names to grant.")
    action_policy_sets: list[str] = Field(
        default_factory=list,
        description="ActionPolicySet names to bind; an explicit list, empty included, is bound as given.",
    )
    kubernetes_grants: list[str] = Field(
        default_factory=list, description="Enabled Kubernetes grant names to bind to this Sandbox ServiceAccount."
    )
    thread_defaults: ThreadDefaults | None = Field(
        default=None, description="Reusable Thread defaults for future sessions in this Sandbox."
    )
    bootstrap: str = Field(default="", max_length=65_536, description="Runner initialization script for this Sandbox.")


class Condition(BaseModel):
    """A Kubernetes status condition, as the Sandbox controller and the kubelet report them."""

    model_config = ConfigDict(extra="ignore")

    type: str
    status: str
    reason: str | None = None
    message: str | None = None


class ContainerStatus(BaseModel):
    """One container of the Pod: which of the kubelet's three states it is in, and why."""

    model_config = ConfigDict(extra="forbid")

    name: str
    state: str = Field(description="waiting, running, or terminated.")
    reason: str | None = None
    message: str | None = None
    ready: bool
    restart_count: int


class PodStatus(BaseModel):
    """What the kubelet says about the Sandbox's Pod; absent while no Pod exists."""

    model_config = ConfigDict(extra="forbid")

    phase: str | None
    ip: str | None
    node_name: str | None
    reason: str | None = None
    message: str | None = None
    conditions: list[Condition]
    containers: list[ContainerStatus]


class SandboxView(BaseModel):
    """One inventory row: the Sandbox's identity plus what it and its Pod say."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The Sandbox name, and its Pod's; the handle for every operation.")
    uid: UUID = Field(description="The API server's identity of this Sandbox; what an owned binding references.")
    state: ProvisioningState
    created_at: datetime
    operating_mode: OperatingMode
    conditions: list[Condition] = Field(description="The Sandbox's own status conditions.")
    node_name: str | None = Field(default=None, description="Where the Sandbox controller placed the Pod.")
    service_account: ServiceAccountRef = Field(
        description="The ServiceAccount its Pod runs as, read off the Sandbox: the subject every "
        "egress and action-policy binding names it by."
    )
    binding: SandboxBinding | None = Field(
        default=None, description="The stored concrete Thread defaults and bootstrap selected for this Sandbox."
    )
    kubernetes_grants: list[ResolvedGrant]
    kubernetes_grants_ready: bool
    kubernetes_grant_error: str | None
    deleting: bool = False
    pod: PodStatus | None = None


class SandboxDestination(BaseModel):
    """A caller's requested resource, never proof of authority. No app Thread or supplied URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: ServiceAccountRef
    sandbox: DnsName
    sandbox_uid: UUID


class SessionDestination(SandboxDestination):
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


