"""ID system for properties/grading.

Provides strongly-typed IDs with namespace separation:
- BaseIssueID: Un-namespaced IDs (used in specimens, critique)
- TruePositiveID, FalsePositiveID, InputIssueID: NewType wrappers for type safety

All IDs are Pydantic-validated. BaseIssueID cannot contain colons (reserved
for legacy string serialization).

NewTypes provide compile-time type safety (mypy distinguishes them) while
remaining strings at runtime (work as JSON dict keys).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NewType, TypeAlias

from pydantic import BeforeValidator, PlainSerializer, constr

# Shared identity serializer for all string-based Annotated types
# Preserves string value unchanged during serialization
_STR_IDENTITY_SERIALIZER = PlainSerializer(lambda x: x, return_type=str, when_used="json")


# =============================================================================
# Base Issue ID (un-namespaced)
# =============================================================================


def _reject_colon(v: Any) -> Any:
    """Validator rejecting colons (reserved for namespace separator in legacy code)."""
    if isinstance(v, str) and ":" in v:
        raise ValueError(f"BaseIssueID cannot contain colon (reserved for namespaces): {v!r}")
    return v


# Base issue ID type (used in specimens, critique definitions)
# Pattern: lowercase alphanumeric, underscore, hyphen only
# Length: 5-40 characters
# No colons (reserved for namespace separator)
# ruff: noqa: UP040 - TypeAlias required for mypy compatibility with complex Annotated types
BaseIssueID: TypeAlias = Annotated[  # type: ignore[valid-type]  # mypy limitation with complex Annotated
    constr(pattern=r"^[a-z0-9_-]+$", min_length=5, max_length=40),
    BeforeValidator(_reject_colon),
    _STR_IDENTITY_SERIALIZER,
]


# =============================================================================
# Snapshot Slug
# =============================================================================

# Base validated snapshot slug type (internal)
# Pattern: {project}/{date-sequence}
#   - project: lowercase alphanumeric, underscore, hyphen (e.g., "ducktape", "crush", "misc")
#   - date-sequence: typically YYYY-MM-DD-NN or YYYY-MM-DD-name (e.g., "2025-11-26-00", "2025-08-30-internal_db")
# Constraint: EXACTLY ONE SLASH for consistent directory depth in runs/
#
# ruff: noqa: UP040 - TypeAlias required for mypy compatibility
_SnapshotSlugBase: TypeAlias = Annotated[  # type: ignore[valid-type]
    constr(
        pattern=r"^[a-z0-9_-]+/[a-z0-9_-]+$",
        min_length=3,  # Minimum: "a/b"
        max_length=100,  # Reasonable upper bound
    ),
    _STR_IDENTITY_SERIALIZER,
]

# Public snapshot slug type (NewType for nominal type safety)
# Compile-time distinct from bare str, runtime is validated _SnapshotSlugBase string
SnapshotSlug = NewType("SnapshotSlug", _SnapshotSlugBase)  # type: ignore[valid-newtype]
"""Snapshot slug ID. Compile-time distinct from str, runtime is validated string."""


# =============================================================================
# Namespaced IDs (NewType for type safety)
# =============================================================================

# NewType creates nominal types for mypy (compile-time type safety)
# At runtime, these are just BaseIssueID strings (work as JSON dict keys)
# Type is implied by position in data structure

# Note: TruePositiveID and FalsePositiveID have been moved to grader/models.py
# as they are internal to the grader subsystem

InputIssueID = NewType("InputIssueID", BaseIssueID)  # type: ignore[valid-newtype]
"""Input critique ID. Compile-time distinct from other ID types, runtime is BaseIssueID string."""


# =============================================================================
# Snapshot Slug Utilities
# =============================================================================


def split_snapshot_slug(slug: SnapshotSlug) -> tuple[str, str]:
    """Split snapshot slug into repo and version components.

    Args:
        slug: Snapshot slug like "ducktape/2025-11-26-00"

    Returns:
        Tuple of (repo, version) e.g., ('ducktape', '2025-11-26-00')

    Example:
        >>> repo, version = split_snapshot_slug(SnapshotSlug("ducktape/2025-11-26-00"))
        >>> repo
        'ducktape'
        >>> version
        '2025-11-26-00'
    """
    parts = str(slug).split("/", 1)
    return parts[0], parts[1]


def get_snapshot_manifest_path(base_path: Path, slug: SnapshotSlug) -> Path:
    """Get synthetic manifest path for bundle URL resolution.

    Returns a synthetic file path inside the snapshot directory used for
    resolving relative bundle URLs. The actual file doesn't need to exist;
    it's just a reference point for URL resolution.

    Args:
        base_path: Specimens base directory
        slug: Snapshot slug like "ducktape/2025-11-26-00"

    Returns:
        Path to synthetic _snapshot file used for bundle URL resolution

    Example:
        >>> base = Path("/path/to/specimens")
        >>> get_snapshot_manifest_path(base, SnapshotSlug("ducktape/2025-11-26-00"))
        PosixPath('/path/to/specimens/ducktape/2025-11-26-00/_snapshot')
    """
    repo, version = split_snapshot_slug(slug)
    return (base_path / repo / version / "_snapshot").resolve()
