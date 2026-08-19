"""Fail-closed Console contract for the Kubernetes API proxy.

The proxy sends the caller's original Haku bearer plus Kubernetes' canonical
request attributes and the minimal equivalent PolicyRule. The temporary-grant
lookup deliberately remains a TODO in this draft: until it exists, every
well-formed request is denied with 501 and therefore cannot reach Kubernetes.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/internal/kubernetes", tags=["kubernetes-proxy"])


class RequestAttributes(BaseModel):
    resource_request: bool
    verb: str
    api_group: str = ""
    api_version: str = ""
    namespace: str = ""
    resource: str = ""
    subresource: str = ""
    name: str = ""
    path: str
    field_selector: str = ""
    label_selector: str = ""


class PolicyRule(BaseModel):
    api_groups: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    verbs: list[str]
    resource_names: list[str] = Field(default_factory=list)
    non_resource_urls: list[str] = Field(default_factory=list)


class AuthorizationRequest(BaseModel):
    attributes: RequestAttributes
    required_rules: list[PolicyRule] = Field(min_length=1)


class AuthorizationResponse(BaseModel):
    allowed: bool
    reason: str | None = None
    lease_id: str | None = None
    expires_at: datetime.datetime | None = None


@router.post("/authorize", response_model=AuthorizationResponse)
async def authorize_kubernetes_request(
    body: AuthorizationRequest, authorization: Annotated[str | None, Header()] = None
) -> AuthorizationResponse:
    """Authorize one already-canonicalized Kubernetes request.

    TODO(#4428): resolve ``authorization`` through the existing Agent authority,
    look up active temporary grants, compare their canonical rules with
    ``body.required_rules``, and return the earliest matching grant expiry.

    The bearer is intentionally sent in the header, never copied into the JSON
    body or logs. This stub fails closed until the grant implementation lands.
    """

    del body
    if (
        authorization is None
        or not authorization.startswith("Bearer ")
        or not authorization.removeprefix("Bearer ").strip()
    ):
        raise HTTPException(status_code=401, detail="Bearer authorization is required")
    raise HTTPException(status_code=501, detail="temporary Kubernetes grant authorization is not implemented")
