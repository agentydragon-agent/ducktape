"""OIDC settings and cookie names shared with deployment configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SECURE_COOKIE = "__Host-agentplane_session"
INSECURE_COOKIE = "agentplane_session"


class OIDCSettings(BaseSettings):
    """Relying-party settings, from AGENTPLANE_OIDC_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="AGENTPLANE_OIDC_", frozen=True)

    issuer: str = Field(description="Per-provider issuer, e.g. https://auth.example/application/o/agentplane/.")
    client_id: str
    client_secret: str
    session_secret: str = Field(description="Signs the session cookie; minted with the client in Terraform.")
    public_base_url: str = Field(description="The app's public origin, which the redirect URI is built from.")
    session_max_seconds: int = Field(
        default=604800, gt=0, description="How long a login lasts at most, however it is used."
    )
    session_idle_seconds: int = Field(
        default=86400, gt=0, description="How long a login lasts without an authenticated request."
    )
    session_activity_step_seconds: int = Field(
        default=300,
        gt=0,
        description="Activity moves the idle deadline only once it would move by more than this, so a "
        "burst of requests does not each rewrite the session row; the idle timeout holds to within it.",
    )
    token_renew_before_seconds: int = Field(
        default=30,
        ge=0,
        description="Renew the login access token once it is this close to expiry, so it cannot lapse "
        "between the check and the provider reading it.",
    )
