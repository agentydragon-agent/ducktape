"""Generic OAuth2 provider: authorization URL, code exchange, token refresh."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlparse

import httpx
import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    name: str = Field(description="Provider identifier used in URL paths and env var prefixes")
    display_name: str = Field(description="Human-readable provider name for the UI")
    authorize_url: str = Field(description="OAuth2 authorization endpoint (unused for provider_type=plaid)")
    token_url: str = Field(description="OAuth2 token endpoint")
    scopes: list[str] = Field(description="OAuth2 scopes to request (Plaid: maps to products)")
    redirect_uri: str = Field(description="OAuth2 redirect URI")
    secret_name: str = Field(description="K8s secret name for storing tokens")
    secret_annotations: dict[str, str] = Field(
        default_factory=dict, description="Annotations to add to the token secret"
    )
    refresh_margin_seconds: int = Field(default=3600, description="Seconds before expiry to trigger refresh")
    extra_auth_params: dict[str, str] = Field(default_factory=dict, description="Extra query params for authorize URL")
    provider_type: Literal["oauth2", "plaid"] = Field(default="oauth2", description="Provider flow type")


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = Field(default="Bearer")
    expires_at: datetime
    scope: str


class BrokerConfig(BaseModel):
    target_namespace: str | None = Field(
        default=None, description="K8s namespace to write token secrets to (auto-detected from pod if omitted)"
    )
    providers: list[ProviderConfig] = Field(description="OAuth2 provider configurations")

    @classmethod
    def from_file(cls, path: Path) -> "BrokerConfig":
        return cls.model_validate(yaml.safe_load(path.read_text()))


class GenericOAuth2Provider:
    def __init__(self, config: ProviderConfig, client_id: str, client_secret: str) -> None:
        self.config = config
        self.client_id = client_id
        self.client_secret = client_secret

    def build_authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            **self.config.extra_auth_params,
        }
        return f"{self.config.authorize_url}?{urlencode(params)}"

    def generate_state(self) -> str:
        return secrets.token_urlsafe(32)

    async def exchange_code(self, code: str) -> TokenData:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.config.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.config.redirect_uri,
                },
            )
            response.raise_for_status()
            return _parse_token_response(response.json())

    async def refresh_tokens(self, refresh_token: str) -> TokenData:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.config.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            response.raise_for_status()
            token = _parse_token_response(response.json())
            # Google omits refresh_token on refresh responses — preserve the old one
            if not token.refresh_token:
                token = token.model_copy(update={"refresh_token": refresh_token})
            return token

    def needs_refresh(self, token: TokenData) -> bool:
        margin = timedelta(seconds=self.config.refresh_margin_seconds)
        return datetime.now(UTC) >= token.expires_at - margin


def _parse_token_response(data: dict) -> TokenData:
    expires_in = data.get("expires_in", 2592000)
    return TokenData(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        token_type=data.get("token_type", "Bearer"),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scope=data.get("scope", ""),
    )


class PlaidProvider(GenericOAuth2Provider):
    """Plaid Link provider.

    Plaid uses a JS widget flow rather than a standard OAuth2 redirect:
    1. Server calls /link/token/create to get a link_token.
    2. Browser renders a page with the Plaid Link JS widget.
    3. User links their bank; for OAuth institutions the bank redirects to
       redirect_uri?oauth_state_id=<id> (server re-renders the widget with
       receivedRedirectUri to resume the session).
    4. On success the widget calls onSuccess(public_token); the page POSTs it
       to our /callback/plaid endpoint.
    5. Server exchanges the public_token for an access_token here.

    Plaid access_tokens never expire, so needs_refresh() always returns False.
    """

    def _plaid_host(self) -> str:
        parsed = urlparse(self.config.token_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def create_link_token(self, state: str) -> str:
        """Create a Plaid link_token. `state` is stored server-side for CSRF."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._plaid_host()}/link/token/create",
                json={
                    "client_id": self.client_id,
                    "secret": self.client_secret,
                    "user": {"client_user_id": "owner"},
                    "products": self.config.scopes,
                    "country_codes": ["US"],
                    "language": "en",
                    "redirect_uri": self.config.redirect_uri,
                },
            )
            response.raise_for_status()
            return response.json()["link_token"]

    async def exchange_public_token(self, public_token: str) -> TokenData:
        """Exchange a Plaid public_token for a permanent access_token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.config.token_url,
                json={"client_id": self.client_id, "secret": self.client_secret, "public_token": public_token},
            )
            response.raise_for_status()
            data = response.json()
        # Plaid access_tokens have no expiry; use a far-future sentinel.
        return TokenData(
            access_token=data["access_token"],
            refresh_token="",
            token_type="Bearer",
            expires_at=datetime.now(UTC) + timedelta(days=36500),
            scope=" ".join(self.config.scopes),
        )

    def needs_refresh(self, token: TokenData) -> bool:
        return False
