"""Compose Agent bearer and Operator browser-session authentication for Haku's MCP server."""

from __future__ import annotations

import datetime
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken, AuthProvider, TokenVerifier
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import HTTPConnection

from haku.console.agent_bearer import AgentBearerResolver
from haku.console.agents.authorization import PostgresAgentAuthority, StaticAgentRejectedError, fingerprint_static_token
from haku.console.chat_models import SessionStatus
from haku.console.config import MCP_PATH, Settings
from haku.console.database_schema import Conversation, Session
from haku.console.mcp_auth.fastmcp_adapter import (
    AgentActorResolutionUnavailableError,
    AgentGrantAuthorityUnavailableError,
    BearerVerificationUnavailableError,
    HakuAgentOAuthProxy,
    HakuFailurePreservingMultiAuth,
    HakuMcpActorResolver,
    OperatorSessionAuthenticationError,
    StaticAgentActorResolver,
    assert_fastmcp_adapter_compatibility,
)
from haku.console.operator_auth import operator_session_for_identity_store
from haku.console.operator_identity_store import PostgresOperatorIdentityStore
from haku.console.tool_call_actor import AgentActor, OperatorActor
from haku.console.x.launch_identity import LaunchAgentRejectedError
from mcp_infra.authentik_auth.provider import DEFAULT_VALID_SCOPES
from mcp_infra.persistence import OAuthClientStorage, build_shared_client_storage

_STATIC_BINDING_CLIENT_ID_PREFIX = "haku-static-binding:"
_CHAT_SESSION_CLIENT_ID_PREFIX = "haku-chat-session:"
_MCP_SESSION_STATUSES = (SessionStatus.READY, SessionStatus.RESPONDING)


@dataclass(frozen=True, slots=True)
class StaticAgentCredentialRegistry:
    """Configured static credential fingerprints, without retaining raw bearers."""

    fingerprints: tuple[bytes, ...]

    def configured_fingerprint(self, token: str) -> bytes | None:
        try:
            presented = fingerprint_static_token(token)
        except ValueError:
            return None
        return next(
            (fingerprint for fingerprint in self.fingerprints if hmac.compare_digest(presented, fingerprint)), None
        )


@dataclass(frozen=True, slots=True)
class _SessionAgentAuthorization:
    session_id: UUID
    agent_id: UUID
    binding_id: UUID
    operator_id: UUID
    access_profile_id: str


@dataclass(frozen=True, slots=True)
class _ResolvedAgentBearer:
    actor: AgentActor
    client_id: str


class _StaticAgentBearerSource:
    def __init__(self, authority: PostgresAgentAuthority, credentials: StaticAgentCredentialRegistry) -> None:
        self._authority = authority
        self._credentials = credentials

    async def resolve(self, token: str, *, record_seen: bool = False) -> _ResolvedAgentBearer | None:
        fingerprint = self._credentials.configured_fingerprint(token)
        if fingerprint is None:
            return None
        authorization = await self._authority.static_authorization_for_fingerprint(
            fingerprint=fingerprint, record_seen=record_seen
        )
        return _ResolvedAgentBearer(
            actor=AgentActor(
                agent_id=authorization.agent_id,
                operator_id=authorization.operator_id,
                binding_id=authorization.binding_id,
                access_profile_id=authorization.access_profile_id,
            ),
            client_id=f"{_STATIC_BINDING_CLIENT_ID_PREFIX}{authorization.binding_id}",
        )


class _SessionAgentBearerSource:
    """Resolve a live Console session bearer through the canonical launch authority."""

    def __init__(self, authority: PostgresAgentAuthority, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._authority = authority
        self._sessions = sessions

    async def resolve(self, token: str, *, record_seen: bool = False) -> _ResolvedAgentBearer | None:
        try:
            fingerprint = fingerprint_static_token(token)
        except ValueError:
            return None
        now = datetime.datetime.now(datetime.UTC)
        try:
            async with self._sessions.begin() as db:
                row = (
                    await db.execute(
                        select(
                            Session.session_id,
                            Session.operator_id,
                            Session.agent_binding_id,
                            Conversation.agent_id,
                            Conversation.access_profile_id,
                            Conversation.runtime_kind,
                        )
                        .join(Conversation, Conversation.conversation_id == Session.conversation_id)
                        .where(
                            Session.bridge_token_fingerprint == fingerprint,
                            Session.status.in_(_MCP_SESSION_STATUSES),
                            Session.bridge_connected_at.is_not(None),
                            Session.lease_expires_at.is_not(None),
                            Session.lease_expires_at > now,
                        )
                    )
                ).one_or_none()
                if (
                    row is None
                    or row.agent_binding_id is None
                    or row.agent_id is None
                    or row.access_profile_id is None
                    or row.runtime_kind is None
                ):
                    return None
                active = await self._authority.launch_authorization(
                    db,
                    operator_id=row.operator_id,
                    agent_id=row.agent_id,
                    access_profile_id=row.access_profile_id,
                    binding_id=row.agent_binding_id,
                )
                authorization = _SessionAgentAuthorization(
                    session_id=row.session_id,
                    agent_id=active.agent_id,
                    binding_id=active.binding_id,
                    operator_id=active.operator_id,
                    access_profile_id=row.access_profile_id,
                )
                return _ResolvedAgentBearer(
                    actor=AgentActor(
                        agent_id=authorization.agent_id,
                        operator_id=authorization.operator_id,
                        binding_id=authorization.binding_id,
                        access_profile_id=authorization.access_profile_id,
                        session_id=authorization.session_id,
                    ),
                    client_id=f"{_CHAT_SESSION_CLIENT_ID_PREFIX}{authorization.session_id}",
                )
        except (LaunchAgentRejectedError, ValueError):
            return None
        except (AgentGrantAuthorityUnavailableError, SQLAlchemyError):
            raise AgentGrantAuthorityUnavailableError from None


class _CompositeAgentBearerResolver(TokenVerifier, StaticAgentActorResolver):
    """One canonical static/session bearer authority shared by MCP and the kube proxy."""

    def __init__(self, sources: tuple[Callable[..., Awaitable[_ResolvedAgentBearer | None]], ...]) -> None:
        super().__init__()
        self._sources = sources

    async def _resolve(self, token: str, *, record_seen: bool = False) -> _ResolvedAgentBearer | None:
        unavailable = False
        for source in self._sources:
            try:
                resolved = await source(token, record_seen=record_seen)
            except AgentGrantAuthorityUnavailableError:
                unavailable = True
                continue
            except (StaticAgentRejectedError, ValueError):
                continue
            if resolved is not None:
                return resolved
        if unavailable:
            raise AgentGrantAuthorityUnavailableError
        return None

    async def resolve_agent(self, token: str) -> AgentActor | None:
        resolved = await self._resolve(token)
        return None if resolved is None else resolved.actor

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            resolved = await self._resolve(token)
        except AgentGrantAuthorityUnavailableError as error:
            raise BearerVerificationUnavailableError("Agent authorization is temporarily unavailable") from error
        if resolved is None:
            return None
        return AccessToken(token=token, client_id=resolved.client_id, scopes=[], expires_at=None, claims={})

    async def resolve_static_actor(self, access_token: AccessToken) -> AgentActor | None:
        resolved = await self._resolve(access_token.token, record_seen=True)
        if resolved is None or resolved.client_id != access_token.client_id:
            return None
        return resolved.actor


def build_agent_bearer_resolver(
    *,
    agent_authority: PostgresAgentAuthority,
    static_credentials: StaticAgentCredentialRegistry,
    session_tokens: async_sessionmaker[AsyncSession] | None = None,
) -> _CompositeAgentBearerResolver:
    """Compose configured static and exact-session bearer authorities."""

    sources: list[Callable[..., Awaitable[_ResolvedAgentBearer | None]]] = []
    if static_credentials.fingerprints:
        sources.append(_StaticAgentBearerSource(agent_authority, static_credentials).resolve)
    if session_tokens is not None:
        sources.append(_SessionAgentBearerSource(agent_authority, session_tokens).resolve)
    return _CompositeAgentBearerResolver(tuple(sources))


@dataclass(frozen=True)
class StaticMcpAuth:
    provider: AuthProvider
    static_actor_resolver: StaticAgentActorResolver
    agent_bearer_resolver: AgentBearerResolver


@dataclass(frozen=True)
class OAuthMcpAuth:
    provider: AuthProvider
    storage: OAuthClientStorage
    static_actor_resolver: StaticAgentActorResolver | None
    agent_bearer_resolver: AgentBearerResolver


type McpAuth = StaticMcpAuth | OAuthMcpAuth


@dataclass(frozen=True, slots=True)
class McpBearerAgentResolver:
    """Resolve every verified MCP bearer family to a canonical Agent actor.

    This is deliberately bearer-only. The MCP transport separately accepts a
    DB-revalidated Operator browser session, but that session is not a bearer
    credential and must never authorize Kubernetes API proxy requests.
    """

    provider: AuthProvider
    actors: HakuMcpActorResolver

    async def resolve_agent(self, token: str) -> AgentActor | None:
        access = await self.provider.verify_token(token)
        if access is None:
            return None
        try:
            return await self.actors.resolve_agent_bearer(access)
        except AgentActorResolutionUnavailableError as error:
            raise BearerVerificationUnavailableError("Agent authorization is temporarily unavailable") from error
        except ToolError:
            return None


class _OperatorMcpSessionAuthenticator:
    """Turn the console's DB-revalidated browser session into an MCP Operator principal."""

    def __init__(self, settings: Settings, identity_store: PostgresOperatorIdentityStore) -> None:
        self._mcp_path = MCP_PATH
        self._public_origin = settings.public_base_url.rstrip("/")
        self._identity_store = identity_store

    async def __call__(self, conn: HTTPConnection) -> OperatorActor | None:
        if conn.url.path != self._mcp_path:
            return None
        session = await operator_session_for_identity_store(conn, self._identity_store)
        if session is None:
            return None
        if conn.headers.get("origin") != self._public_origin:
            raise OperatorSessionAuthenticationError("operator MCP requests require the console's exact Origin")
        return OperatorActor(operator_id=session.operator_id)


def build_auth(
    settings: Settings,
    *,
    agent_authority: PostgresAgentAuthority,
    static_credentials: StaticAgentCredentialRegistry,
    operator_identity_store: PostgresOperatorIdentityStore,
    session_tokens: async_sessionmaker[AsyncSession] | None = None,
    agent_bearer_resolver: _CompositeAgentBearerResolver | None = None,
) -> McpAuth:
    """Compose FastMCP protocol auth with Haku's canonical Agent authority.

    FastMCP owns DCR, PKCE, callback, client, and token-family storage. Haku's OAuth adapter
    delegates every product authorization decision to ``agent_authority``. Static credentials use
    the same authority and are accepted only when their exact fingerprint-backed binding is active.
    """
    assert_fastmcp_adapter_compatibility()
    agent_bearer_resolver = agent_bearer_resolver or build_agent_bearer_resolver(
        agent_authority=agent_authority, static_credentials=static_credentials, session_tokens=session_tokens
    )
    has_bearer = bool(static_credentials.fingerprints or session_tokens is not None)
    operator_session_authenticator = _OperatorMcpSessionAuthenticator(settings, operator_identity_store)
    if settings.mcp_oauth is not None:
        storage = build_shared_client_storage(settings.mcp_oauth.persistence)
        config = settings.mcp_oauth.as_authentik_auth_config(public_base_url=settings.public_base_url)
        proxy = HakuAgentOAuthProxy(
            config_url=f"{config.normalized_issuer()}/.well-known/openid-configuration",
            client_id=config.oidc_client_id,
            client_secret=config.oidc_client_secret,
            base_url=config.normalized_public_base_url(),
            resource_base_url=settings.public_base_url,
            client_storage=storage,
            expected_issuer=config.oidc_issuer,
            grant_authority=agent_authority,
        )
        proxy.update_default_scopes(DEFAULT_VALID_SCOPES)
        return OAuthMcpAuth(
            provider=HakuFailurePreservingMultiAuth(
                server=proxy,
                verifiers=[agent_bearer_resolver],
                operator_session_authenticator=operator_session_authenticator,
            ),
            storage=storage,
            static_actor_resolver=agent_bearer_resolver if has_bearer else None,
            agent_bearer_resolver=agent_bearer_resolver,
        )
    if not has_bearer:
        raise ValueError(
            "haku-console /mcp has no configured credential: set at least one static Agent "
            "(config_file `static_agents`) or `mcp_oauth`"
        )
    return StaticMcpAuth(
        provider=HakuFailurePreservingMultiAuth(
            server=agent_bearer_resolver, verifiers=[], operator_session_authenticator=operator_session_authenticator
        ),
        static_actor_resolver=agent_bearer_resolver,
        agent_bearer_resolver=agent_bearer_resolver,
    )
