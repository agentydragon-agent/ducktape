"""Console-side authorization for the Haku Kubernetes API proxy.

The proxy authenticates an Agent with a Haku bearer, but the Kubernetes
authorization decision is made by a Kubernetes SubjectAccessReview (SAR).  A
SAR is always issued for the deploy-configured subject below; request callers
cannot supply a Kubernetes username or groups.

This module deliberately has no database or grant state.  The bearer resolver
is supplied by the Console composition root and is responsible for resolving
the presented credential to a currently active Haku Agent.  Kubernetes
authorization is disabled when no config is supplied, and every client/config
failure is surfaced as an unavailable authority so callers fail closed.
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from kubernetes_asyncio import client as k8s_client, config as k8s_config
from kubernetes_asyncio.client import ApiClient, AuthorizationV1Api
from kubernetes_asyncio.config.config_exception import ConfigException
from pydantic import BaseModel, ConfigDict, Field

from haku.console.config import KubernetesAuthorizationConfig, KubernetesAuthorizationSubject
from haku.console.tool_call_actor import AgentActor


class KubernetesAuthorizationUnavailableError(RuntimeError):
    """The Console cannot make an authoritative Kubernetes decision."""


class KubernetesBearerRejectedError(RuntimeError):
    """The presented Haku bearer does not resolve to an active Agent."""


class RequestAttributes(BaseModel):
    """Kubernetes' canonical interpretation of one HTTP request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_request: bool
    verb: str = Field(min_length=1)
    api_group: str = ""
    api_version: str = ""
    namespace: str = ""
    resource: str = ""
    subresource: str = ""
    name: str = ""
    path: str = Field(min_length=1)
    field_selector: str = ""
    label_selector: str = ""


class PolicyRule(BaseModel):
    """The proxy's legacy rule projection, retained for wire compatibility.

    SAR authorization uses ``RequestAttributes`` directly.  Keeping this
    field in the request lets the proxy roll independently of Console and
    avoids making a caller-controlled PolicyRule part of the decision.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_groups: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    verbs: list[str] = Field(min_length=1)
    resource_names: list[str] = Field(default_factory=list)
    non_resource_urls: list[str] = Field(default_factory=list)


class AuthorizationRequest(BaseModel):
    """Proxy-to-Console authorization request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attributes: RequestAttributes
    required_rules: list[PolicyRule] = Field(default_factory=list, min_length=1)


class AuthorizationResponse(BaseModel):
    """The small fail-closed response understood by the proxy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason: str | None = None
    decision_id: str = Field(min_length=1)
    valid_until: datetime.datetime | None = None


@dataclass(frozen=True, slots=True)
class SubjectAccessReviewResult:
    allowed: bool
    reason: str | None = None


class SubjectAccessReviewClient(Protocol):
    async def review(
        self, *, subject: KubernetesAuthorizationSubject, attributes: RequestAttributes
    ) -> SubjectAccessReviewResult: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class KubernetesClients:
    api: ApiClient
    authorization: AuthorizationV1Api


class KubernetesSubjectAccessReviewClient:
    """Lazily connect to the in-cluster Kubernetes Authorization API."""

    def __init__(self, clients: KubernetesClients | None = None) -> None:
        self._clients = clients
        self._lock = asyncio.Lock()

    async def _connected(self) -> KubernetesClients:
        async with self._lock:
            if self._clients is None:
                configuration = k8s_client.Configuration()
                try:
                    k8s_config.load_incluster_config(client_configuration=configuration)
                except ConfigException as error:
                    raise KubernetesAuthorizationUnavailableError(
                        "Kubernetes in-cluster configuration is unavailable"
                    ) from error
                api = ApiClient(configuration=configuration)
                self._clients = KubernetesClients(api=api, authorization=AuthorizationV1Api(api))
            return self._clients

    async def review(
        self, *, subject: KubernetesAuthorizationSubject, attributes: RequestAttributes
    ) -> SubjectAccessReviewResult:
        resource_attributes = None
        non_resource_attributes = None
        if attributes.resource_request:
            resource_attributes = k8s_client.V1ResourceAttributes(
                group=attributes.api_group,
                version=attributes.api_version,
                namespace=attributes.namespace,
                resource=attributes.resource,
                subresource=attributes.subresource,
                name=attributes.name,
                verb=attributes.verb,
            )
        else:
            non_resource_attributes = k8s_client.V1NonResourceAttributes(path=attributes.path, verb=attributes.verb)
        request = k8s_client.V1SubjectAccessReview(
            api_version="authorization.k8s.io/v1",
            kind="SubjectAccessReview",
            spec=k8s_client.V1SubjectAccessReviewSpec(
                user=subject.username,
                groups=list(subject.groups),
                resource_attributes=resource_attributes,
                non_resource_attributes=non_resource_attributes,
            ),
        )
        try:
            response = await (await self._connected()).authorization.create_subject_access_review(request)
        except KubernetesAuthorizationUnavailableError:
            raise
        except Exception as error:
            raise KubernetesAuthorizationUnavailableError("Kubernetes authorization API is unavailable") from error
        status = response.status
        if status is None or status.allowed is None:
            raise KubernetesAuthorizationUnavailableError("Kubernetes returned an incomplete authorization response")
        if getattr(status, "evaluation_error", None):
            raise KubernetesAuthorizationUnavailableError("Kubernetes authorization evaluation reported an error")
        if status.allowed and getattr(status, "denied", False):
            raise KubernetesAuthorizationUnavailableError("Kubernetes returned a contradictory authorization response")
        return SubjectAccessReviewResult(allowed=bool(status.allowed), reason=status.reason)

    async def aclose(self) -> None:
        if self._clients is not None:
            await self._clients.api.close()
            self._clients = None


class KubernetesAuthorizationService:
    """Authenticate a Haku bearer, then use its deploy-selected profile's fixed SAR subject."""

    def __init__(
        self,
        *,
        config: KubernetesAuthorizationConfig | None,
        resolve_agent: Callable[[str], Awaitable[AgentActor | None]],
        sar_client: SubjectAccessReviewClient | None = None,
    ) -> None:
        self._config = config
        self._resolve_agent = resolve_agent
        self._sar_client = sar_client

    async def authorize(self, *, bearer: str, request: AuthorizationRequest) -> AuthorizationResponse:
        token = _bearer_token(bearer)
        if token is None:
            raise KubernetesBearerRejectedError("Bearer authorization is required")
        try:
            actor = await self._resolve_agent(token)
        except KubernetesAuthorizationUnavailableError:
            raise
        except Exception as error:
            raise KubernetesAuthorizationUnavailableError("Haku Agent authority is unavailable") from error
        if actor is None:
            raise KubernetesBearerRejectedError("Haku rejected the caller credential")
        if self._config is None:
            raise KubernetesAuthorizationUnavailableError("Kubernetes authorization is not configured")
        profile_id = actor.access_profile_id
        subject = self._config.subjects_by_access_profile.get(profile_id) if profile_id is not None else None
        if subject is None:
            raise KubernetesAuthorizationUnavailableError(
                "Kubernetes authorization is not configured for the Agent access profile"
            )
        client = self._sar_client
        if client is None:
            client = KubernetesSubjectAccessReviewClient()
            self._sar_client = client
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                result = await client.review(subject=subject, attributes=request.attributes)
        except TimeoutError as error:
            raise KubernetesAuthorizationUnavailableError("Kubernetes authorization timed out") from error
        return AuthorizationResponse(allowed=result.allowed, reason=result.reason, decision_id=f"sar:{uuid4()}")

    async def aclose(self) -> None:
        if self._sar_client is not None:
            await self._sar_client.aclose()


def _bearer_token(value: str) -> str | None:
    scheme, separator, token = value.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        return None
    return token.strip()
