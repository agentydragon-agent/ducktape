"""Shared construction and creation of Agent Sandbox claims."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from util.kubernetes import CustomObjectsClient

CLAIM_GROUP = "extensions.agents.x-k8s.io"
CLAIM_API_VERSION = "v1beta1"
CLAIMS_PLURAL = "sandboxclaims"


class _ClaimMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    labels: dict[str, str]
    annotations: dict[str, str] | None = None


class _ClaimWarmPoolRef(BaseModel):
    name: str


class _ClaimLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    shutdown_policy: str = Field(alias="shutdownPolicy")
    shutdown_time: str = Field(alias="shutdownTime")


class _ClaimEnvVar(BaseModel):
    name: str
    value: str


class _ClaimSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    warm_pool_ref: _ClaimWarmPoolRef = Field(alias="warmPoolRef")
    lifecycle: _ClaimLifecycle
    env: list[_ClaimEnvVar] | None = None


class _SandboxClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    api_version: str = Field(alias="apiVersion")
    kind: str
    metadata: _ClaimMetadata
    spec: _ClaimSpec


@dataclass(frozen=True, slots=True)
class SandboxClaimSpec:
    """Inputs for one claim, including env injected only when the claim is created.

    The env payload is creation-time-only: an adoption path leaves the existing claim, including
    its env, untouched. Callers retain ownership of their orchestration and supply their own
    labels, annotations, and lifecycle policy here.
    """

    namespace: str
    name: str
    warm_pool: str
    labels: Mapping[str, str]
    annotations: Mapping[str, str]
    shutdown_policy: str
    shutdown_time: datetime
    env: Mapping[str, str] | None = None


def format_shutdown_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_sandbox_claim(spec: SandboxClaimSpec) -> dict[str, Any]:
    return _SandboxClaim(
        apiVersion=f"{CLAIM_GROUP}/{CLAIM_API_VERSION}",
        kind="SandboxClaim",
        metadata={
            "name": spec.name,
            "labels": dict(spec.labels),
            "annotations": dict(spec.annotations) or None,
        },
        spec={
            "warmPoolRef": {"name": spec.warm_pool},
            "lifecycle": {
                "shutdownPolicy": spec.shutdown_policy,
                "shutdownTime": format_shutdown_time(spec.shutdown_time),
            },
            "env": (
                [{"name": name, "value": value} for name, value in spec.env.items()]
                if spec.env is not None
                else None
            ),
        },
    ).model_dump(by_alias=True, exclude_none=True)


async def create_sandbox_claim(custom_objects: CustomObjectsClient, spec: SandboxClaimSpec) -> dict[str, Any]:
    """Build and create a claim; adoption remains the caller's orchestration concern."""

    return await custom_objects.create_namespaced_custom_object(
        CLAIM_GROUP, CLAIM_API_VERSION, spec.namespace, CLAIMS_PLURAL, build_sandbox_claim(spec)
    )
