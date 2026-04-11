"""Shared configuration loaded from .claude_hooks/config.yaml.

Repo-level config file that all hooks read. Configures OTEL tracing,
profiles, and other shared settings. Secrets are handled by env scripts
(devinfra/secrets/*.sh), not by this config file.

Environment variables (DUCKTAPE_CLAUDE_HOOKS_*) override values from this file.
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
        """Apply DUCKTAPE_CLAUDE_HOOKS_OTEL_* env var overrides.

        TODO: Rationalize env var override pattern — consider using pydantic-settings
        with a unified DUCKTAPE_CLAUDE_HOOKS_ prefix instead of ad-hoc os.environ.get().
        """
        return OtelConfig(
            endpoint=os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT", self.endpoint),
            bearer_token=os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN", self.bearer_token),
        )


class K8sConfig(BaseModel):
    """K8s cluster connection config for kubeconfig generation."""

    server: str = Field(description="K8s API server URL")
    service_account: str = Field(description="ServiceAccount name for kubeconfig user and context")
    service_account_namespace: str = Field(default="default", description="Namespace of the ServiceAccount")
    namespace: str = Field(description="Default namespace for kubectl operations")


class BazelRemoteProxyConfig(BaseModel):
    target: str = Field(description="host:port to connect to, e.g. 'remote.buildbuddy.io:443'")


class ProfileConfig(BaseModel):
    bazel_remote_proxy: BazelRemoteProxyConfig | None = Field(
        default=None, description="UDS proxy for Bazel --remote_proxy (remote execution + cache). Null = disabled."
    )
    bazel_bes_proxy: BazelRemoteProxyConfig | None = Field(
        default=None,
        description="BES interceptor: gRPC service that inspects events and forwards to BuildBuddy. Null = disabled.",
    )
    bes_nudge_remote_execution: bool = Field(
        default=False,
        description="When BES interceptor is active, post a mailbox nudge if a build/test invocation "
        "lacks --remote_executor. Encourages agent to use `bb remote`.",
    )
    write_kubeconfig: bool = Field(
        default=True,
        description="Write a service-account kubeconfig and export KUBECONFIG. "
        "Set to false in CLI profile when the user has their own ~/.kube/config.",
    )
    install_mkcert: bool = Field(default=False, description="Install mkcert and generate localhost TLS cert.")
    install_apt_packages: bool = Field(default=False, description="Install native dev packages via apt.")
    setup_docker: bool = Field(default=False, description="Set up Docker daemon under supervisor.")
    bazel_warmup: str | None = Field(
        default=None,
        description="Bazel warmup command after session start. 'info' for JVM warmup, "
        "arbitrary command string for cache warmup, null to disable.",
    )
    env_exports: str | None = Field(
        default=None, description="Inline shell content appended verbatim to the session env file."
    )
    env_script: str | None = Field(
        default=None,
        description="Repo-relative path to a shell script whose stdout is appended to the session env file.",
    )


class DefaultProfiles(BaseModel):
    """Which named profile to use by default for each mode."""

    cli: str
    web: str


class PreCommitConfig(BaseModel, frozen=True):
    """Pre-commit hook behavior configuration."""

    auto_apply_hooks: frozenset[str] = Field(
        default_factory=frozenset,
        description="Hook IDs whose file modifications are kept (not reverted). "
        "All other hooks' modifications are reverted and reported as diffs.",
    )
    show_report_diffs: bool = Field(
        default=False, description="Show unified diffs from report-only hooks in the PostToolUse output."
    )
    show_hook_output: bool = Field(
        default=False, description="Show stdout/stderr from failing hooks in the PostToolUse output."
    )


class HookConfig(BaseModel):
    """Top-level hook config file (.claude_hooks/config.yaml)."""

    k8s: K8sConfig | None = None
    otel: OtelConfig | None = None
    pre_commit: PreCommitConfig | None = None
    profiles: dict[str, ProfileConfig]
    default_profiles: DefaultProfiles

    def resolve_profile(self, web_mode: bool, override: str | None = None) -> ProfileConfig:
        """Resolve a profile by name. Override > default for mode > error."""
        name = override or (self.default_profiles.web if web_mode else self.default_profiles.cli)
        if name not in self.profiles:
            available = ", ".join(sorted(self.profiles))
            raise KeyError(f"Profile {name!r} not found (available: {available})")
        return self.profiles[name]

    @classmethod
    def load(cls, config_path: Path) -> HookConfig:
        """Load hook config from YAML file."""
        raw = yaml.safe_load(config_path.read_text())
        return cls.model_validate(raw)

    @classmethod
    def load_from_repo(cls, root: Path) -> HookConfig:
        """Load hook config from repo root. Raises FileNotFoundError if absent."""
        config_path = root / HOOKS_DOTDIR / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Hook config not found: {config_path}")
        config = cls.load(config_path)
        if config.otel:
            config = config.model_copy(update={"otel": config.otel.with_env_overrides()})
        return config
