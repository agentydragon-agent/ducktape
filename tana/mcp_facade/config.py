"""Settings for the public Tana MCP OAuth facade."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_infra.authentik_auth.auth import AuthentikAuthConfig


class ServerSettings(BaseSettings):
    """Config for the Tana MCP OAuth facade."""

    model_config = SettingsConfigDict(env_prefix="TANA_MCP_FACADE_", env_nested_delimiter="__")

    auth: AuthentikAuthConfig
    downstream_url: str = Field(description="Internal bearer-authenticated MCP endpoint for Tana.")
    static_bearer_token: str = Field(description="Server-held bearer token injected on the downstream hop.")
    host: str = "0.0.0.0"
    port: int = 8765
