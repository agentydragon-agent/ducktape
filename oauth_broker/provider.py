"""Generic OAuth2 provider: authorization URL, code exchange, token refresh."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    name: str = Field(description="Provider identifier used in URL paths and env var prefixes")
    display_name: str = Field(description="Human-readable provider name for the UI")
    authorize_url: str = Field(description="OAuth2 authorization endpoint")
    token_url: str = Field(description="OAuth2 token endpoint")
    scopes: list[str] = Field(description="OAuth2 scopes to request")
    redirect_uri: str = Field(description="OAuth2 redirect URI")
    secret_name: str = Field(description="K8s secret name for storing tokens")
    refresh_margin_seconds: int = Field(default=3600, description="Seconds before expiry to trigger refresh")


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = Field(default="Bearer")
    expires_at: datetime
    scope: str


class BrokerConfig(BaseModel):
    target_namespace: str = Field(default="openclaw-sandbox", description="K8s namespace to write token secrets to")
    providers: list[ProviderConfig] = Field(description="OAuth2 provider configurations")

    @classmethod
    def from_file(cls, path: Path) -> "BrokerConfig":
        return cls.model_validate_json(path.read_text())


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
            return _parse_token_response(response.json())

    def needs_refresh(self, token: TokenData) -> bool:
        margin = timedelta(seconds=self.config.refresh_margin_seconds)
        return datetime.now(UTC) >= token.expires_at - margin


def _parse_token_response(data: dict) -> TokenData:
    expires_in = data.get("expires_in", 2592000)
    return TokenData(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        token_type=data.get("token_type", "Bearer"),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scope=data.get("scope", ""),
    )
