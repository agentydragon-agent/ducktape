"""Configuration for the Airlock server.

The bulk of settings are loaded from a YAML config file (CONFIG_PATH env var,
default /etc/airlock/config.yaml).

Config file format (YAML):

  backends:
    kubeapi_admin:
      url: http://kubeapi-admin-exec-mcp:8766/mcp
    files:
      command: /usr/bin/file-server
      args: [--mcp]

  public_base_url: "https://airlock.example.com"
  oidc_issuer: "https://auth.example.com/application/o/airlock/"
  db_path: "/data/airlock.db"      # optional, defaults to /data/airlock.db

Each backend entry matches fastmcp's MCPConfig mcpServers entry format.
Backend keys are validated as MCPMountPrefix (lowercase alphanumeric + underscore).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastmcp.mcp_config import MCPServerTypes, RemoteMCPServer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from airlock.models import WaitMode, YieldAfterMs
from airlock.oauth.provider import GenericOAuth2Provider, OAuthConfig, PlaidProvider, PlaidProviderConfig, Provider
from mcp_infra.prefix import MCPMountPrefix


class Settings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    backends: dict[MCPMountPrefix, MCPServerTypes]
    public_base_url: str
    db_path: Path = Path("/data/airlock.db")
    predicate_path: Path = Field(
        description=(
            "Path to a Python module exporting "
            "decide(server_namespace, tool_name, arguments) → Approved|Denied|NeedsHumanDecision."
        )
    )
    oidc_issuer: str
    oidc_client_id: str
    default_wait_mode: WaitMode = YieldAfterMs(timeout_ms=0)
    oauth: OAuthConfig = Field(description="OAuth token broker configuration")
    host: str = "0.0.0.0"
    port: int

    @field_validator("public_base_url", mode="after")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @classmethod
    def load(cls) -> Settings:
        config_path = Path(os.environ.get("CONFIG_PATH", "/etc/airlock/config.yaml"))
        data = yaml.safe_load(config_path.read_text())
        settings = cls.model_validate(data)
        exec_token = os.environ.get("EXEC_BACKEND_TOKEN")
        if exec_token:
            for backend in settings.backends.values():
                if isinstance(backend, RemoteMCPServer) and "Authorization" not in backend.headers:
                    backend.headers["Authorization"] = f"Bearer {exec_token}"
        return settings


def build_oauth_providers(oauth_config: OAuthConfig) -> dict[str, Provider]:
    """Construct OAuth provider instances from config + env vars."""
    providers: dict[str, Provider] = {}
    for p in oauth_config.providers:
        prefix = p.name.upper()
        client_id = os.environ[f"{prefix}_CLIENT_ID"]
        client_secret = os.environ[f"{prefix}_CLIENT_SECRET"]
        if isinstance(p, PlaidProviderConfig):
            providers[p.name] = PlaidProvider(p, client_id, client_secret)
        else:
            providers[p.name] = GenericOAuth2Provider(p, client_id, client_secret)
    return providers
