from __future__ import annotations

"""Shared helpers for ID prefixing and checks in properties tooling.

Provides a single source of truth for the canonical/critique ID prefixes and
small utilities to normalize and inspect IDs.
"""

CANON_TP_PREFIX = "canon_tp_"
CANON_FP_PREFIX = "canon_fp_"
CRIT_PREFIX = "crit_"


def _ensure_prefixed(value: str | None, prefix: str) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s if s.startswith(prefix) else f"{prefix}{s}"


def ensure_crit_id(value: str | None) -> str | None:
    return _ensure_prefixed(value, CRIT_PREFIX)


def ensure_canon_tp_id(value: str | None) -> str | None:
    return _ensure_prefixed(value, CANON_TP_PREFIX)


def ensure_canon_fp_id(value: str | None) -> str | None:
    return _ensure_prefixed(value, CANON_FP_PREFIX)


def is_crit_id(value: str | None) -> bool:
    return bool(value) and str(value).startswith(CRIT_PREFIX)


def is_canon_tp_id(value: str | None) -> bool:
    return bool(value) and str(value).startswith(CANON_TP_PREFIX)


def is_canon_fp_id(value: str | None) -> bool:
    return bool(value) and str(value).startswith(CANON_FP_PREFIX)


def strip_crit_prefix(value: str | None) -> str:
    s = "" if value is None else str(value)
    return s.removeprefix(CRIT_PREFIX)


def ensure_with_prefix(value: str | None, prefix: str) -> str | None:
    """Normalize an ID to include the expected prefix.

    Recognizes known prefixes (canon_tp_, canon_fp_, crit_) and delegates to the
    dedicated helpers. For any other prefix, falls back to a generic concatenation.
    """
    if prefix == CANON_TP_PREFIX:
        return ensure_canon_tp_id(value)
    if prefix == CANON_FP_PREFIX:
        return ensure_canon_fp_id(value)
    if prefix == CRIT_PREFIX:
        return ensure_crit_id(value)
    return _ensure_prefixed(value, prefix)
