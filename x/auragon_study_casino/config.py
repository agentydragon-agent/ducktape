"""Settings for the Study Casino backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    session_secret: bytes
    public_url: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDY_CASINO_")

    database_url: str | None = Field(
        default=None,
        description=(
            "SQLAlchemy URL for the casino state database "
            "(e.g. `postgresql+psycopg://user:pass@host/db`). "
            "When unset, falls back to SQLite at `data_dir/casino.db` "
            "(for tests and local dev)."
        ),
    )
    data_dir: Path = Field(
        default=Path("/data"),
        description=(
            "Directory for the SQLite fallback when `database_url` is unset. Ignored when `database_url` is set."
        ),
    )
    host: str = "0.0.0.0"
    port: int = 8080
    frontend_dist_dir: Path | None = Field(
        default=None,
        description=(
            "Directory containing the built frontend bundle (index.html, main.js, "
            "sw.js, manifest.webmanifest, icon.svg). Defaults to `./frontend/dist` "
            "next to this module; override for tests or alternate layouts."
        ),
    )

    # OIDC — all four must be set together to enable authentication.
    # When unset, the app accepts all requests as user "default" (dev/test mode).
    oidc_issuer: str | None = Field(
        default=None, description="OIDC issuer URL, e.g. https://auth.allegedly.works/application/o/study-casino"
    )
    oidc_client_id: str | None = Field(default=None, description="OAuth2 client_id registered in Authentik")
    oidc_client_secret: str | None = Field(default=None, description="OAuth2 client_secret (confidential client)")
    session_secret: str | None = Field(
        default=None, min_length=32, description="Secret key for HMAC-signed session cookies. Must be ≥32 chars."
    )
    public_url: str = Field(
        default="https://casino.allegedly.works",
        description="Public base URL of this app, used to build the OIDC redirect_uri.",
    )

    def resolved_database_url(self) -> str:
        """Return the effective SQLAlchemy URL — explicit `database_url` or SQLite fallback."""
        if self.database_url is not None:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'casino.db'}"

    def oidc_config(self) -> OidcConfig | None:
        """Return fully-typed OIDC config if all four fields are set, else None."""
        if not (self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret and self.session_secret):
            return None
        return OidcConfig(
            issuer=self.oidc_issuer,
            client_id=self.oidc_client_id,
            client_secret=self.oidc_client_secret,
            session_secret=self.session_secret.encode(),
            public_url=self.public_url,
        )
