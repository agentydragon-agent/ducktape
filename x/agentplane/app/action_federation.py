"""Request-bound Authentik JWT-bearer federation, following Haku hostexec's grant shape.

No global operator client/token cache, static BFF bearer, or workload-token promotion. Provider-
scoped subjects need an explicit reviewed mapping; identical strings are never assumed continuity.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp_infra.authentik_auth.oidc_principal import (
    AuthentikOidcPrincipalResolver,
    InvalidOidcPrincipalError,
    OidcPrincipalVerificationUnavailableError,
)
from x.agentplane.action_service.client import OperatorActionServiceClient
from x.agentplane.action_service.operator_oidc import OperatorOidcSettings
from x.agentplane.app.oidc import OIDCSettings, OperatorSession


class OperatorFederationError(Exception):
    """Fixed public failure codes only; never provider bodies or token material."""


class ActionFederationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service_url: str
    token_endpoint: str
    login_jwks_uri: str
    target: OperatorOidcSettings
    subject_mapping: dict[str, str] = Field(min_length=1)
    scope: str = Field(min_length=1)

    @field_validator("service_url")
    @classmethod
    def service_endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("service_url must be an HTTP(S) URL without credentials, query, or fragment")
        return value

    @field_validator("token_endpoint")
    @classmethod
    def secure_exchange_endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            not url.hostname
            or url.username is not None
            or url.password is not None
            or url.fragment
            or url.query
            or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"}))
        ):
            raise ValueError("token_endpoint must be HTTPS (loopback HTTP is allowed for tests)")
        return value


class FederatedOperatorActions:
    def __init__(self, config: ActionFederationSettings, oidc: OIDCSettings, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http
        self._login_issuer = oidc.issuer
        self._upstream = AuthentikOidcPrincipalResolver(
            expected_issuer=oidc.issuer,
            discovered_issuer=oidc.issuer,
            jwks_uri=config.login_jwks_uri,
            signing_algorithms=["RS256"],
            client_id=oidc.client_id,
        )
        self._target = config.target.resolver()
        if not set(config.subject_mapping.values()) <= config.target.subjects:
            raise ValueError("federation mappings must name authorized target subjects")

    def for_session(self, session: OperatorSession) -> OperatorActionServiceClient:
        return OperatorActionServiceClient(self._http, _SessionToken(self, session))

    async def exchange(self, session: OperatorSession) -> str:
        if session.issuer != self._login_issuer or session.expires_at <= time.time() or session.access_token is None:
            raise OperatorFederationError("operator_reauthentication_required")
        target_subject = self._config.subject_mapping.get(session.subject)
        if target_subject is None:
            raise OperatorFederationError("operator_federation_subject_not_authorized")
        try:
            upstream = await self._upstream.resolve(
                {"access_token": session.access_token.get_secret_value(), "token_type": "Bearer"}
            )
            if (upstream.issuer, upstream.subject) != (session.issuer, session.subject):
                raise OperatorFederationError("operator_federation_identity_mismatch")
            # Authlib mutates token state: create a fresh OAuth client for each exchange.
            async with AsyncOAuth2Client(client_id=self._config.target.audience, timeout=10) as client:
                token = await client.fetch_token(
                    url=self._config.token_endpoint,
                    grant_type="client_credentials",
                    client_assertion_type="urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    client_assertion=session.access_token.get_secret_value(),
                    scope=self._config.scope,
                )
            downstream = await self._target.resolve(token)
            if downstream.subject != target_subject:
                raise OperatorFederationError("operator_federation_identity_mismatch")
            access_token = token["access_token"]
            if not isinstance(access_token, str):
                raise OperatorFederationError("operator_federation_token_invalid")
            return access_token
        except InvalidOidcPrincipalError:
            raise OperatorFederationError("operator_federation_token_invalid") from None
        except (OAuthError, httpx.HTTPError, OidcPrincipalVerificationUnavailableError, ValueError):
            raise OperatorFederationError("operator_federation_exchange_failed") from None


class _SessionToken:
    def __init__(self, provider: FederatedOperatorActions, session: OperatorSession) -> None:
        self._provider = provider
        self._session = session

    async def token(self) -> str:
        return await self._provider.exchange(self._session)
