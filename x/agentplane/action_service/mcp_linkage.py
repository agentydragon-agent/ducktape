"""PostgreSQL-backed operator OAuth linkage for configured remote MCP servers."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from x.agentplane.action_service.catalog import Key
from x.agentplane.action_service.db import McpLinkageFlowRow, McpServerLinkageRow, SessionMaker
from x.agentplane.action_service.models import Principal, PrincipalRole


class McpProvider(StrEnum):
    GITHUB = "github"
    KUBERNETES = "kubernetes"


class McpOAuthServer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: Key
    provider: McpProvider
    server_url: str = Field(min_length=1)
    authorization_endpoint: str = Field(min_length=1)
    token_endpoint: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret_file: Path | None = None
    redirect_uri: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)


class McpLinkageStart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scopes: list[str] = Field(default_factory=list)


class McpLinkageStatus(StrEnum):
    UNLINKED = "unlinked"
    LINKED = "linked"
    EXPIRED = "expired"


class McpLinkageView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: str
    provider: McpProvider
    server_url: str
    status: McpLinkageStatus
    revision: int
    scopes: list[str]
    expires_at: datetime | None
    linked_at: datetime | None
    linked_by: str | None


class McpLinkageStartView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    flow_id: UUID
    authorization_url: str
    expires_at: datetime


class McpLinkageError(Exception):
    pass


class McpLinkageNotFoundError(McpLinkageError):
    pass


class McpLinkageConflictError(McpLinkageError):
    pass


class McpLinkageAuthority:
    """One shared active token family per configured MCP server, persisted in Postgres."""

    def __init__(
        self, sessions: SessionMaker, servers: dict[str, McpOAuthServer], http: httpx.AsyncClient | None = None
    ) -> None:
        self._sessions = sessions
        self._servers = dict(servers)
        self._http = http

    def servers(self) -> dict[str, McpOAuthServer]:
        return dict(self._servers)

    async def list(self) -> list[McpLinkageView]:
        return [await self.status(server_id) for server_id in self._servers]

    async def status(self, server_id: str) -> McpLinkageView:
        server = self._server(server_id)
        async with self._sessions() as db:
            row = await db.get(McpServerLinkageRow, server_id)
        return _view(server, row)

    async def start(self, server_id: str, request: McpLinkageStart, operator: Principal) -> McpLinkageStartView:
        self._require_operator(operator)
        server = self._server(server_id)
        scopes = _scopes(request.scopes or server.scopes, server.scopes)
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=10)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        flow_id = uuid4()
        async with self._sessions.begin() as db:
            db.add(
                McpLinkageFlowRow(
                    id=flow_id,
                    server_id=server_id,
                    state_hash=_digest(state),
                    verifier=verifier,
                    operator_principal=operator.key,
                    scopes=scopes,
                    expires_at=expires_at,
                    consumed_at=None,
                )
            )
        query = {
            "response_type": "code",
            "client_id": server.client_id,
            "redirect_uri": server.redirect_uri,
            "state": state,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        }
        if scopes:
            query["scope"] = " ".join(scopes)
        return McpLinkageStartView(
            flow_id=flow_id,
            authorization_url=f"{server.authorization_endpoint}?{urlencode(query)}",
            expires_at=expires_at,
        )

    async def callback(self, state: str, code: str) -> McpLinkageView:
        if not state or not code:
            raise McpLinkageConflictError("OAuth callback is missing state or code")
        async with self._sessions.begin() as db:
            flow = await db.scalar(
                select(McpLinkageFlowRow).where(McpLinkageFlowRow.state_hash == _digest(state)).with_for_update()
            )
            if flow is None or flow.consumed_at is not None or flow.expires_at <= datetime.now(UTC):
                raise McpLinkageConflictError("OAuth linkage flow is invalid or expired")
            server = self._server(flow.server_id)
            verifier = flow.verifier
            flow.consumed_at = datetime.now(UTC)
            token = await self._exchange(server, code, verifier, flow.scopes)
            expires_at = _expiry(token)
            current = await db.get(McpServerLinkageRow, server.server_id, with_for_update=True)
            revision = (current.revision + 1) if current is not None else 1
            if current is None:
                current = McpServerLinkageRow(
                    server_id=server.server_id,
                    provider=server.provider.value,
                    server_url=server.server_url,
                    revision=revision,
                    scopes=flow.scopes,
                    token=token,
                    expires_at=expires_at,
                    linked_at=datetime.now(UTC),
                    linked_by=flow.operator_principal,
                )
                db.add(current)
            else:
                current.provider = server.provider.value
                current.server_url = server.server_url
                current.revision = revision
                current.scopes = flow.scopes
                current.token = token
                current.expires_at = expires_at
                current.linked_at = datetime.now(UTC)
                current.linked_by = flow.operator_principal
            await db.flush()
            return _view(server, current)

    async def disconnect(self, server_id: str, operator: Principal) -> McpLinkageView:
        self._require_operator(operator)
        server = self._server(server_id)
        async with self._sessions.begin() as db:
            row = await db.get(McpServerLinkageRow, server_id, with_for_update=True)
            if row is not None:
                row.revision += 1
                row.token_ciphertext = None
                row.expires_at = None
                row.linked_at = None
                row.linked_by = None
            return _view(server, row)

    async def access_token(self, server_id: str, expected_revision: int) -> str:
        """Resolve a token only after dispatch has fenced the linkage revision."""
        server = self._server(server_id)
        async with self._sessions() as db:
            row = await db.get(McpServerLinkageRow, server_id)
        if row is None or row.token is None or row.revision != expected_revision:
            raise McpLinkageConflictError("MCP linkage changed or is not connected")
        if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
            raise McpLinkageConflictError("MCP linkage token has expired; reconnect the server")
        del server
        token = row.token
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise McpLinkageConflictError("MCP linkage token is invalid")
        return access_token

    def _server(self, server_id: str) -> McpOAuthServer:
        try:
            return self._servers[server_id]
        except KeyError:
            raise McpLinkageNotFoundError("unknown MCP server") from None

    @staticmethod
    def _require_operator(operator: Principal) -> None:
        if operator.role is not PrincipalRole.OPERATOR:
            raise McpLinkageError("operator authority is required")

    async def _exchange(self, server: McpOAuthServer, code: str, verifier: str, scopes: list[str]) -> dict[str, object]:
        client_secret = server.client_secret_file.read_text().strip() if server.client_secret_file else None
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": server.redirect_uri,
            "client_id": server.client_id,
            "code_verifier": verifier,
        }
        if scopes:
            data["scope"] = " ".join(scopes)
        if client_secret:
            data["client_secret"] = client_secret
        client = self._http or httpx.AsyncClient(timeout=15)
        close = self._http is None
        try:
            response = await client.post(server.token_endpoint, data=data)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise McpLinkageConflictError("MCP OAuth token exchange failed") from None
        finally:
            if close:
                await client.aclose()
        if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
            raise McpLinkageConflictError("MCP OAuth provider returned no access token")
        return body


def _view(server: McpOAuthServer, row: McpServerLinkageRow | None) -> McpLinkageView:
    if row is None or row.token_ciphertext is None:
        status = McpLinkageStatus.UNLINKED
        revision = row.revision if row else 0
        scopes = row.scopes if row else server.scopes
        expires_at = None
        linked_at = None
        linked_by = None
    elif row.expires_at is not None and row.expires_at <= datetime.now(UTC):
        status = McpLinkageStatus.EXPIRED
        revision, scopes, expires_at, linked_at, linked_by = (
            row.revision,
            row.scopes,
            row.expires_at,
            row.linked_at,
            row.linked_by,
        )
    else:
        status = McpLinkageStatus.LINKED
        revision, scopes, expires_at, linked_at, linked_by = (
            row.revision,
            row.scopes,
            row.expires_at,
            row.linked_at,
            row.linked_by,
        )
    return McpLinkageView(
        server_id=server.server_id,
        provider=server.provider,
        server_url=server.server_url,
        status=status,
        revision=revision,
        scopes=scopes,
        expires_at=expires_at,
        linked_at=linked_at,
        linked_by=linked_by,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _scopes(requested: list[str], allowed: list[str]) -> list[str]:
    if not set(requested) <= set(allowed):
        raise McpLinkageConflictError("requested OAuth scopes are not configured for this MCP server")
    return list(dict.fromkeys(requested))


def _expiry(token: dict[str, object]) -> datetime | None:
    expires_in = token.get("expires_in")
    if isinstance(expires_in, (int, float)):
        return datetime.now(UTC) + timedelta(seconds=float(expires_in))
    return None
