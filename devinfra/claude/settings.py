"""Centralized configuration for claude using Pydantic Settings.

Hook-related configuration (feature flags, port overrides, k8s token).
Path computations live in session_paths.py.

Environment Variables (in priority order):
1. DUCKTAPE_CLAUDE_HOOKS_* - Direct override for specific setting
2. XDG_CACHE_HOME / XDG_CONFIG_HOME - XDG standard directories (via platformdirs)
3. Platform defaults (Linux: ~/.cache, ~/.config; macOS: ~/Library/Caches, etc.)
"""

import importlib.resources
import os
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources.abc import Traversable
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Config files bundled with the package (infrastructure config: bazelrc, env)
CONFIG_FILES: Traversable = importlib.resources.files("devinfra.claude.config")

# TODO: Rename prefix to DUCKTAPE_CLAUDE_ to match new dir name.
# Environment variable prefix (matches model_config.env_prefix)
ENV_PREFIX = "DUCKTAPE_CLAUDE_HOOKS_"


def _env_name(field: str) -> str:
    """Compute env var name from field name. Pattern: ENV_PREFIX + field.upper()"""
    return f"{ENV_PREFIX}{field.upper()}"


# Environment variable names (used by tests and env_file.py)
ENV_SUPERVISOR_PORT = _env_name("supervisor_port")
ENV_AUTH_PROXY_PORT = _env_name("auth_proxy_port")
ENV_SETUP_DOCKER = _env_name("setup_docker")
ENV_SESSION_DIR = _env_name("session_dir")


def is_web_mode() -> bool:
    """Check if running in Claude Code web mode (CLAUDE_CODE_REMOTE=true)."""
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


class ProxyMode(StrEnum):
    """Bazel proxy routing mode."""

    UDS = "uds"
    TCP = "tcp"


@dataclass(frozen=True)
class BazelWarmupDisabled:
    """No Bazel warmup after session setup."""


@dataclass(frozen=True)
class BazelWarmupInfo:
    """Warm up by running `bazel info` (starts JVM only)."""


@dataclass(frozen=True)
class BazelWarmupCommand:
    """Warm up by running a configurable Bazel command (starts JVM + populates cache)."""

    command: str


BazelWarmup = BazelWarmupDisabled | BazelWarmupInfo | BazelWarmupCommand


def _parse_bazel_warmup(value: object) -> BazelWarmup:
    """Parse a string into a BazelWarmup variant.

    'disabled' → BazelWarmupDisabled, 'info' → BazelWarmupInfo,
    anything else → BazelWarmupCommand(command=value).
    """
    if isinstance(value, (BazelWarmupDisabled, BazelWarmupInfo, BazelWarmupCommand)):
        return value
    if not isinstance(value, str):
        raise ValueError(f"expected str, got {type(value).__name__}")
    match value:
        case "disabled":
            return BazelWarmupDisabled()
        case "info":
            return BazelWarmupInfo()
        case _:
            return BazelWarmupCommand(command=value)


class HookSettings(BaseSettings):
    """Configuration for claude via environment variables.

    Feature flags, port overrides, and k8s token. Path computations
    are in SessionPaths (session_paths.py).
    """

    model_config = SettingsConfigDict(env_prefix="DUCKTAPE_CLAUDE_HOOKS_", env_file_encoding="utf-8")

    # Port overrides (used by tests for free-port isolation)
    supervisor_port: int = Field(default=19001, description="Supervisor TCP port")
    auth_proxy_port: int = Field(default=18081, description="Auth proxy port")

    # Profile override (env var DUCKTAPE_CLAUDE_HOOKS_PROFILE)
    profile: str | None = Field(default=None, description="Override profile name from config.yaml")

    # Feature flags (enable/disable installations)
    install_mkcert: bool = Field(default=True, description="Install mkcert and generate localhost TLS cert")
    install_apt_packages: bool = True
    setup_docker: bool = Field(default=True, description="Set up Docker daemon under supervisor")

    k8s_token: str | None = Field(default=None, description="K8s SA token for reading secrets from cluster")
    age_key: str | None = Field(
        default=None,
        description="Age private key (AGE-SECRET-KEY-...) for SOPS decryption. "
        "Used by Claude agent in Claude Code web to decrypt repo secrets locally.",
    )

    bazel_warmup: Annotated[BazelWarmup, BeforeValidator(_parse_bazel_warmup)] = Field(
        default=BazelWarmupInfo(),
        description="Bazel warmup: 'disabled', 'info' (bazel info), or a command string (e.g. \"query 'tests(//...)')\")",
    )

    proxy_mode: ProxyMode = Field(
        default=ProxyMode.UDS,
        description=(
            "Bazel proxy mode. 'uds': route gRPC via --remote_proxy/--bes_proxy UDS, "
            "BCR uses native JAVA_TOOL_OPTIONS proxy. 'tcp': route all Bazel traffic "
            "through localhost TCP HTTP CONNECT proxy (legacy)."
        ),
    )
    # Per-session output directory. Exported as DUCKTAPE_CLAUDE_HOOKS_SESSION_DIR so
    # subprocesses (e.g. bazel_wrapper) pick it up automatically via pydantic-settings.
    # Baked into the bazel/bazelisk shell wrapper at install time so it survives
    # into pre-commit and other subprocess invocations that don't source the env file.
    session_dir: str | None = Field(default=None, description="Per-session output directory (for bazel_wrapper env)")
