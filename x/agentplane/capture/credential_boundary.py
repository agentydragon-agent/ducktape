"""Credential delivery that never serializes a virtual key into capture artifacts."""

from __future__ import annotations

from pathlib import Path


class CredentialBoundaryError(ValueError):
    pass


def read_runtime_key(path: Path) -> str:
    """Read a user-provided 0600 credential file without logging its content."""
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise CredentialBoundaryError("credential file must not be group/world accessible")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise CredentialBoundaryError("credential file is empty")
    return key


def credential_environment(*, key: str, provider: str, endpoint: str) -> dict[str, str]:
    """Return only harness-facing environment variables; callers must not record it."""
    if provider == "claude":
        return {"ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_BASE_URL": endpoint}
    if provider == "codex":
        return {"OPENAI_API_KEY": key, "OPENAI_BASE_URL": endpoint}
    raise CredentialBoundaryError(f"unknown provider: {provider}")


def sanitize_environment(environment: dict[str, str]) -> dict[str, str]:
    forbidden = ("KEY", "TOKEN", "AUTH", "SECRET", "PASSWORD", "COOKIE")
    return {key: value for key, value in environment.items() if not any(word in key.upper() for word in forbidden)}
