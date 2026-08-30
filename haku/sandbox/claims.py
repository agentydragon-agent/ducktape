"""Shared construction and creation of Agent Sandbox claims."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from util.kubernetes import CustomObjectsClient

CLAIM_GROUP = "extensions.agents.x-k8s.io"
CLAIM_API_VERSION = "v1beta1"
CLAIMS_PLURAL = "sandboxclaims"


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
    body: dict[str, Any] = {
        "apiVersion": f"{CLAIM_GROUP}/{CLAIM_API_VERSION}",
        "kind": "SandboxClaim",
        "metadata": {"name": spec.name, "labels": dict(spec.labels)},
        "spec": {
            "warmPoolRef": {"name": spec.warm_pool},
            "lifecycle": {
                "shutdownPolicy": spec.shutdown_policy,
                "shutdownTime": format_shutdown_time(spec.shutdown_time),
            },
        },
    }
    if spec.annotations:
        body["metadata"]["annotations"] = dict(spec.annotations)
    if spec.env is not None:
        body["spec"]["env"] = [{"name": name, "value": value} for name, value in spec.env.items()]
    return body


async def create_sandbox_claim(custom_objects: CustomObjectsClient, spec: SandboxClaimSpec) -> dict[str, Any]:
    """Build and create a claim; adoption remains the caller's orchestration concern."""

    return await custom_objects.create_namespaced_custom_object(
        CLAIM_GROUP, CLAIM_API_VERSION, spec.namespace, CLAIMS_PLURAL, build_sandbox_claim(spec)
    )
