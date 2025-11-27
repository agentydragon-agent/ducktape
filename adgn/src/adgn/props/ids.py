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

from typing import Annotated, Any, NewType, TypeAlias

from pydantic import BeforeValidator, PlainSerializer, constr

# =============================================================================
# Shared Serializer
# =============================================================================

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
# Namespaced IDs (NewType for type safety)
# =============================================================================

# NewType creates nominal types for mypy (compile-time type safety)
# At runtime, these are just BaseIssueID strings (work as JSON dict keys)
# Type is implied by position in data structure (true positive keys in canonical_tp_coverage, etc.)

TruePositiveID = NewType("TruePositiveID", BaseIssueID)  # type: ignore[valid-newtype]
"""True positive ID. Compile-time distinct from other ID types, runtime is BaseIssueID string."""

FalsePositiveID = NewType("FalsePositiveID", BaseIssueID)  # type: ignore[valid-newtype]
"""False positive ID. Compile-time distinct from other ID types, runtime is BaseIssueID string."""

InputIssueID = NewType("InputIssueID", BaseIssueID)  # type: ignore[valid-newtype]
"""Input critique ID. Compile-time distinct from other ID types, runtime is BaseIssueID string."""
