"""Fail-closed scanner for candidate fixture bundles.

It intentionally returns only rule names and paths: candidates must never become
logs or test output. This is a promotion boundary, not best-effort redaction.
"""

from __future__ import annotations

import base64
import json
import math
import re
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

_FORBIDDEN_KEYS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "api-key",
        "apikey",
        "api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
        "private_key",
    }
)
_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("bearer", re.compile(rb"\bbearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE)),
    ("basic", re.compile(rb"\bbasic\s+[A-Za-z0-9+/=]{12,}", re.IGNORECASE)),
    ("jwt", re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("anthropic_key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{10,}\b")),
    ("openai_key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
_DECLARED_IDENTIFIER_FIELDS = frozenset({"id", "request_id", "threadId", "turnId", "uuid"})


class SecretScanError(ValueError):
    """A fixture candidate contains forbidden or unscanned material."""


def _entropy(value: bytes) -> float:
    counts = {byte: value.count(byte) for byte in set(value)}
    size = len(value)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def _scan_bytes(raw: bytes, path: str, failures: list[str], *, check_entropy: bool) -> None:
    for name, pattern in _PATTERNS:
        if pattern.search(raw):
            failures.append(f"{path}:{name}")
    if check_entropy:
        for token in re.findall(rb"[A-Za-z0-9_-]{48,}", raw):
            if _entropy(token) >= 4.4:
                failures.append(f"{path}:high_entropy")
                break


def _scan_structured_bytes(raw: bytes, path: str, failures: list[str]) -> bool:
    """Scan JSON or SSE JSON fields, returning whether a schema was recognized."""
    with suppress(UnicodeDecodeError, json.JSONDecodeError):
        _scan_value(json.loads(raw), path, failures)
        return True
    recognized = False
    for index, line in enumerate(raw.splitlines()):
        if not line.startswith(b"data: "):
            continue
        with suppress(UnicodeDecodeError, json.JSONDecodeError):
            _scan_value(json.loads(line[6:]), f"{path}:sse[{index}]", failures)
            recognized = True
    return recognized


def _scan_value(value: Any, path: str, failures: list[str], *, field_name: str | None = None) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                failures.append(f"{path}:non_string_key")
                continue
            lowered = key.lower().replace("_", "-")
            if lowered in _FORBIDDEN_KEYS:
                failures.append(f"{path}.{key}:forbidden_field")
            _scan_value(nested, f"{path}.{key}", failures, field_name=key)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_value(nested, f"{path}[{index}]", failures, field_name=field_name)
    elif isinstance(value, str):
        raw = value.encode("utf-8", "surrogatepass")
        if field_name is not None and field_name.endswith("_base64"):
            try:
                decoded = base64.b64decode(raw, validate=True)
            except ValueError:
                failures.append(f"{path}:invalid_base64")
                return
            # This is the actual raw fixture payload. It gets both signature and
            # high-entropy scanning; its encoded JSON representation does not.
            decoded_path = f"{path}:decoded_base64"
            _scan_bytes(decoded, decoded_path, failures, check_entropy=False)
            if not _scan_structured_bytes(decoded, decoded_path, failures):
                _scan_bytes(decoded, decoded_path, failures, check_entropy=True)
            return
        _scan_bytes(raw, path, failures, check_entropy=field_name not in _DECLARED_IDENTIFIER_FIELDS)


def scan_payload(raw: bytes, path: str) -> list[str]:
    failures: list[str] = []
    # Scan bytes for recognizable credential signatures, but do not classify the
    # serialized capture container's base64 text as a secret-shaped token.
    _scan_bytes(raw, path, failures, check_entropy=False)
    _scan_structured_bytes(raw, path, failures)
    return failures


def scan_files(paths: Iterable[Path]) -> None:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            failures.append(f"{path}:not_regular_file")
            continue
        failures.extend(scan_payload(path.read_bytes(), path.as_posix()))
    if failures:
        raise SecretScanError("fixture scanner rejected material: " + ", ".join(sorted(set(failures))))
