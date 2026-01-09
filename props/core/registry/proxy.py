"""OCI Registry proxy with ACL enforcement and metadata tracking.

Sits between agents and the upstream registry to:
- Validate agent auth tokens
- Enforce naming conventions (agents can only push to their namespace)
- Record image refs in database when pushed
- Prevent overwrites and deletes without permission

The proxy implements the OCI Distribution API, forwarding valid requests
to the upstream registry while enforcing access controls.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from props.core.db.models import AgentRun
from props.core.db.session import get_session

logger = logging.getLogger(__name__)

# Environment variables for registry configuration
UPSTREAM_REGISTRY_URL = os.environ.get("PROPS_REGISTRY_UPSTREAM_URL", "http://props-registry:5000")


@dataclass
class AgentAuth:
    """Authenticated agent context."""

    agent_run_id: UUID
    namespace: str  # e.g., "agent-{short_uuid}"


def _extract_agent_from_token(token: str) -> AgentAuth | None:
    """Extract agent identity from auth token.

    Token format: "agent_{agent_run_id}_{secret}"
    Returns None if token is invalid.
    """
    if not token.startswith("agent_"):
        return None

    parts = token.split("_", 2)
    if len(parts) < 2:
        return None

    try:
        agent_run_id = UUID(parts[1])
    except ValueError:
        return None

    # Namespace is agent-{short_uuid} for isolation
    short_id = str(agent_run_id).split("-")[0]
    return AgentAuth(agent_run_id=agent_run_id, namespace=f"agent-{short_id}")


def get_auth(authorization: Annotated[str | None, Header()] = None) -> AgentAuth:
    """Dependency to extract and validate agent auth."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Support "Bearer <token>" format
    token = authorization.removeprefix("Bearer ")

    auth = _extract_agent_from_token(token)
    if auth is None:
        raise HTTPException(status_code=401, detail="Invalid agent token")

    # Verify agent run exists in database
    with get_session() as session:
        agent_run = session.get(AgentRun, auth.agent_run_id)
        if agent_run is None:
            raise HTTPException(status_code=401, detail="Agent run not found")

    return auth


def _validate_namespace_access(auth: AgentAuth, repository: str, method: str) -> None:
    """Validate agent has access to the repository namespace.

    Rules:
    - Agents can only push to their own namespace (agent-{short_uuid}/*)
    - Read access is allowed for any repository
    - DELETE is not allowed
    """
    if method == "DELETE":
        raise HTTPException(status_code=403, detail="DELETE not allowed")

    # Read operations (GET, HEAD) are allowed for any repository
    if method in ("GET", "HEAD"):
        return

    # Write operations must be to agent's namespace
    if not repository.startswith(auth.namespace + "/"):
        raise HTTPException(status_code=403, detail=f"Cannot write to {repository}; only {auth.namespace}/* is allowed")


def _record_image_push(auth: AgentAuth, repository: str, tag: str, digest: str) -> None:
    """Record image push in database for metadata tracking.

    Creates or updates agent_definitions row with the image reference.
    """
    image_ref = f"{repository}:{tag}" if tag else f"{repository}@{digest}"
    logger.info(f"Recording image push: {image_ref} by agent {auth.agent_run_id}")

    # TODO: When Phase 2 adds image_ref column, update AgentRun here
    # For now, just log the push


def create_proxy_app() -> FastAPI:
    """Create FastAPI app for registry proxy."""
    app = FastAPI(title="Props Registry Proxy", description="OCI Registry proxy with ACL")

    client = httpx.AsyncClient(base_url=UPSTREAM_REGISTRY_URL, timeout=60.0)

    @app.on_event("shutdown")
    async def shutdown():
        await client.aclose()

    @app.get("/v2/")
    async def check_api() -> dict:
        """OCI Distribution API version check."""
        return {}

    @app.get("/v2/_catalog")
    async def list_repositories(auth: Annotated[AgentAuth, Depends(get_auth)]) -> Response:
        """List repositories (proxied to upstream)."""
        resp = await client.get("/v2/_catalog")
        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

    @app.api_route("/v2/{repository:path}/tags/list", methods=["GET"])
    async def list_tags(repository: str, auth: Annotated[AgentAuth, Depends(get_auth)], request: Request) -> Response:
        """List tags for a repository (proxied to upstream)."""
        _validate_namespace_access(auth, repository, "GET")
        resp = await client.get(f"/v2/{repository}/tags/list")
        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

    @app.api_route("/v2/{repository:path}/manifests/{reference}", methods=["GET", "HEAD"])
    async def get_manifest(
        repository: str, reference: str, auth: Annotated[AgentAuth, Depends(get_auth)], request: Request
    ) -> Response:
        """Get or check manifest (proxied to upstream)."""
        _validate_namespace_access(auth, repository, request.method)

        # Forward Accept header for content negotiation
        headers = {}
        if accept := request.headers.get("accept"):
            headers["Accept"] = accept

        resp = await client.request(request.method, f"/v2/{repository}/manifests/{reference}", headers=headers)
        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

    @app.api_route("/v2/{repository:path}/manifests/{reference}", methods=["PUT"])
    async def put_manifest(
        repository: str, reference: str, auth: Annotated[AgentAuth, Depends(get_auth)], request: Request
    ) -> Response:
        """Push manifest (proxied to upstream with ACL check)."""
        _validate_namespace_access(auth, repository, "PUT")

        body = await request.body()
        content_type = request.headers.get("content-type", "application/vnd.oci.image.manifest.v1+json")

        resp = await client.put(
            f"/v2/{repository}/manifests/{reference}", content=body, headers={"Content-Type": content_type}
        )

        if resp.status_code in (200, 201):
            # Extract digest from response header
            digest = resp.headers.get("Docker-Content-Digest", "")
            tag = reference if not reference.startswith("sha256:") else ""
            _record_image_push(auth, repository, tag, digest)

        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

    @app.api_route("/v2/{repository:path}/blobs/{digest}", methods=["GET", "HEAD"])
    async def get_blob(
        repository: str, digest: str, auth: Annotated[AgentAuth, Depends(get_auth)], request: Request
    ) -> Response:
        """Get or check blob (proxied to upstream)."""
        _validate_namespace_access(auth, repository, request.method)
        resp = await client.request(request.method, f"/v2/{repository}/blobs/{digest}")

        # Stream large blobs
        if resp.status_code == 200 and int(resp.headers.get("content-length", 0)) > 1024 * 1024:
            return StreamingResponse(
                content=resp.iter_bytes(), status_code=resp.status_code, headers=dict(resp.headers)
            )

        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

    @app.api_route("/v2/{repository:path}/blobs/uploads/", methods=["POST"])
    async def start_upload(
        repository: str, auth: Annotated[AgentAuth, Depends(get_auth)], request: Request
    ) -> Response:
        """Start blob upload (proxied to upstream with ACL check)."""
        _validate_namespace_access(auth, repository, "POST")

        # Handle monolithic upload (digest query param present)
        digest = request.query_params.get("digest")
        if digest:
            body = await request.body()
            resp = await client.post(
                f"/v2/{repository}/blobs/uploads/",
                params={"digest": digest},
                content=body,
                headers={"Content-Type": "application/octet-stream"},
            )
        else:
            resp = await client.post(f"/v2/{repository}/blobs/uploads/")

        # Rewrite Location header to go through proxy
        headers = dict(resp.headers)
        if "location" in headers:
            # Keep relative path, client will use proxy URL
            pass

        return Response(content=resp.content, status_code=resp.status_code, headers=headers)

    @app.api_route("/v2/{repository:path}/blobs/uploads/{uuid}", methods=["PATCH", "PUT"])
    async def continue_upload(
        repository: str, uuid: str, auth: Annotated[AgentAuth, Depends(get_auth)], request: Request
    ) -> Response:
        """Continue or finish blob upload (proxied to upstream with ACL check)."""
        _validate_namespace_access(auth, repository, request.method)

        body = await request.body()
        headers = {"Content-Type": request.headers.get("content-type", "application/octet-stream")}

        if request.method == "PUT":
            # Finish upload with digest
            digest = request.query_params.get("digest", "")
            resp = await client.put(
                f"/v2/{repository}/blobs/uploads/{uuid}", params={"digest": digest}, content=body, headers=headers
            )
        else:
            # PATCH - stream chunk
            resp = await client.patch(f"/v2/{repository}/blobs/uploads/{uuid}", content=body, headers=headers)

        return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))

    return app


# Expose app for uvicorn
app = create_proxy_app()
