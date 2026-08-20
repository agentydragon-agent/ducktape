"""Typed vocabulary for temporary Kubernetes grants.

This module intentionally contains no request/authentication context.  A grant is owned by an
explicit Agent UUID supplied by its caller and its source tool-call identifier is durable
provenance, not a way to infer the caller.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_serializer, field_validator, model_validator


class KubernetesGrantStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    REVOKED = "revoked"
    EXPIRED = "expired"


_NON_EMPTY = Annotated[str, Field(min_length=1)]


def _clean_values(value: Iterable[str], field_name: str, *, allow_empty: bool = False) -> frozenset[str]:
    values = tuple(item.strip() for item in value)
    if not allow_empty and any(not item for item in values):
        raise ValueError(f"{field_name} must not contain empty values")
    return frozenset(values)


class KubernetesRule(BaseModel):
    """One conservative Kubernetes RBAC-like rule.

    Resource rules use ``api_groups``/``resources``/``verbs`` and optionally
    ``resource_names``.  Non-resource rules use ``non_resource_urls`` and ``verbs``.  The shape
    uses the same concepts as Kubernetes PolicyRule while remaining independent of that transport.
    Any Kubernetes wire-format translation belongs at the transport boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_groups: frozenset[str] = Field(default_factory=frozenset)
    resources: frozenset[str] = Field(default_factory=frozenset)
    verbs: frozenset[_NON_EMPTY] = Field(min_length=1)
    resource_names: frozenset[str] = Field(default_factory=frozenset)
    non_resource_urls: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("api_groups", "resources", "resource_names", "non_resource_urls")
    @classmethod
    def normalize_values(cls, value: frozenset[str], info: ValidationInfo) -> frozenset[str]:
        assert info.field_name is not None
        return _clean_values(value, info.field_name, allow_empty=info.field_name == "api_groups")

    @field_validator("verbs")
    @classmethod
    def normalize_verbs(cls, value: frozenset[str]) -> frozenset[str]:
        return _clean_values(value, "verbs")

    @field_serializer("api_groups", "resources", "verbs", "resource_names", "non_resource_urls")
    def serialize_values(self, value: frozenset[str]) -> list[str]:
        return sorted(value)

    @model_validator(mode="after")
    def validate_kind(self) -> KubernetesRule:
        if self.non_resource_urls:
            if self.api_groups or self.resources or self.resource_names:
                raise ValueError("a Kubernetes rule cannot mix resource and non-resource URL fields")
        elif not self.resources:
            raise ValueError("a Kubernetes resource rule must contain resources")
        return self


class KubernetesGrant(BaseModel):
    """Durable grant returned by the service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: UUID
    agent_id: UUID
    source_tool_call_id: _NON_EMPTY
    rules: tuple[KubernetesRule, ...] = Field(min_length=1)
    status: KubernetesGrantStatus
    created_at: datetime.datetime
    expires_at: datetime.datetime
    ended_at: datetime.datetime | None = None
    end_reason: str | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> KubernetesGrant:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.ended_at is not None and (self.ended_at.tzinfo is None or self.ended_at.utcoffset() is None):
            raise ValueError("ended_at must be timezone-aware")
        if self.status is KubernetesGrantStatus.ACTIVE:
            if self.ended_at is not None or self.end_reason is not None:
                raise ValueError("an active grant cannot have terminal fields")
        elif self.ended_at is None or not self.end_reason or not self.end_reason.strip():
            raise ValueError("a terminal grant requires ended_at and a non-empty end_reason")
        return self


class KubernetesGrantDecision(BaseModel):
    """Result of matching a request against one Agent's currently active grants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    grant_id: UUID | None = None
    expires_at: datetime.datetime | None = None
    reason: str | None = None


class KubernetesGrantError(Exception):
    """Base class for grant-domain failures."""


class KubernetesGrantNotFoundError(KubernetesGrantError, LookupError):
    pass


class KubernetesGrantOwnershipError(KubernetesGrantError, PermissionError):
    pass


class KubernetesGrantSourceError(KubernetesGrantError, ValueError):
    pass
