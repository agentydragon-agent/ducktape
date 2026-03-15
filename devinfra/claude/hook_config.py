"""Shared configuration loaded from .claude_hooks/config.yaml.

This is the repo-level config file that all hooks read. It configures
k8s secrets, OTEL tracing, and other shared settings. Environment
variables (DUCKTAPE_CLAUDE_HOOKS_*) override values from this file.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

HOOKS_DOTDIR = ".claude_hooks"


class OtelConfig(BaseModel):
    """OpenTelemetry configuration."""

    endpoint: str | None = None
    auth_token: str | None = None


class K8sSecretMapping(BaseModel):
    """Maps a single k8s Secret's data keys to env var names."""

    name: str
    data: dict[str, str]  # secret data key -> env var name


class K8sSecretRef(BaseModel):
    """Reference to a single key in a k8s Secret."""

    secret_name: str
    data_key: str


class K8sSecretsConfig(BaseModel):
    """Config for reading secrets from k8s."""

    namespace: str
    secrets: list[K8sSecretMapping]
    buildbuddy_api_key: K8sSecretRef | None = None


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


def load_config(config_path: Path) -> HookConfig:
    """Load hook config from YAML file."""
    raw = yaml.safe_load(config_path.read_text())
    return HookConfig.model_validate(raw)


def load_repo_config(root: Path) -> HookConfig | None:
    """Load hook config from repo root, or None if not found."""
    config_path = root / HOOKS_DOTDIR / "config.yaml"
    return load_config(config_path) if config_path.exists() else None
