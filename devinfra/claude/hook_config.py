"""Shared configuration loaded from .claude_hooks/config.yaml.

Repo-level config file that all hooks read. Configures k8s secrets,
OTEL tracing, and other shared settings. Environment variables
(DUCKTAPE_CLAUDE_HOOKS_*) override values from this file.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

HOOKS_DOTDIR = ".claude_hooks"


class OtelConfig(BaseModel):
    endpoint: str | None = Field(default=None, description="OTLP/HTTP traces endpoint URL")
    bearer_token: str | None = Field(default=None, description="Bearer token for the OTLP endpoint")

    def with_env_overrides(self) -> OtelConfig:
        """Apply DUCKTAPE_CLAUDE_HOOKS_OTEL_* env var overrides."""
        return OtelConfig(
            endpoint=os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT", self.endpoint),
            bearer_token=os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN", self.bearer_token),
        )


class K8sSecretMapping(BaseModel):
    """Maps a single k8s Secret's data keys to env var names."""

    name: str
    data: dict[str, str] = Field(description="Secret data key → env var name")


class K8sSecretRef(BaseModel):
    """Reference to a single key in a k8s Secret."""

    secret_name: str
    data_key: str


class K8sSecretsConfig(BaseModel):
    """Config for reading secrets from k8s."""

    namespace: str
    secrets: list[K8sSecretMapping]
    buildbuddy_api_key: K8sSecretRef | None = None
    otel_bearer_token: K8sSecretRef | None = None


class K8sConfig(BaseModel):
    """K8s cluster connection config."""

    server: str
    service_account: str
    sa_namespace: str = "default"
    namespace: str


class HookConfig(BaseModel):
    """Top-level hook config file (.claude_hooks/config.yaml)."""

    k8s: K8sConfig | None = None
    k8s_secrets: K8sSecretsConfig | None = None
    otel: OtelConfig | None = None

    @classmethod
    def load(cls, config_path: Path) -> HookConfig:
        """Load hook config from YAML file."""
        raw = yaml.safe_load(config_path.read_text())
        return cls.model_validate(raw)

    @classmethod
    def load_from_repo(cls, root: Path) -> HookConfig | None:
        """Load hook config from repo root (with env var overrides), or None if not found."""
        config_path = root / HOOKS_DOTDIR / "config.yaml"
        if not config_path.exists():
            return None
        config = cls.load(config_path)
        if config.otel:
            config = config.model_copy(update={"otel": config.otel.with_env_overrides()})
        return config
