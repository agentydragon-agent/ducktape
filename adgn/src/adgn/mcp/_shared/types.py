"""MCP domain types with Pydantic validation.

Provides strongly-typed, validated types for MCP identifiers and data structures.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints, TypeAdapter
from pydantic_core import core_schema

# ==============================================================================
# MCP Mount Prefix Validation
# ==============================================================================

# Shared identity serializer for string-based Annotated types
# Preserves string value unchanged during JSON serialization
_STR_IDENTITY_SERIALIZER = PlainSerializer(lambda x: x, return_type=str, when_used="json")


class MCPMountPrefix(str):
    """Validated MCP mount prefix (str subclass with validating constructor).

    Used in tool names as: {prefix}_{tool}
    Used in mount operations: compositor.mount_inproc(name=prefix, server=...)

    Pattern: lowercase letter followed by lowercase letters/digits/underscores
    Length: 1-50 characters (all current prefixes are < 20 chars)

    Examples: "runtime", "resources", "policy_reader", "agent_control"

    Validates on construction:
        prefix = MCPMountPrefix("runtime")  # Validates automatically
        # Raises ValidationError if invalid

    Works everywhere strings work:
        - Dict keys, URL segments
        - JSON serializes as plain string
        - f-strings: f"{prefix}_tool"
    """

    __slots__ = ()

    # Module-level adapter for validation
    _adapter: TypeAdapter = TypeAdapter(
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=50)]
    )

    def __new__(cls, value: str) -> MCPMountPrefix:
        """Validate and construct MCPMountPrefix.

        Args:
            value: String to validate as mount prefix

        Returns:
            Validated MCPMountPrefix (str subclass)

        Raises:
            ValidationError: If value doesn't match constraints
        """
        validated = cls._adapter.validate_python(value)
        return str.__new__(cls, validated)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        """Provide Pydantic core schema for validation in models.

        This tells Pydantic how to validate MCPMountPrefix when used in model fields.
        """
        return core_schema.no_info_after_validator_function(
            cls, core_schema.str_schema(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=50)
        )


# ==============================================================================
# Container/Runtime Types
# ==============================================================================


class ContainerImageInfo(BaseModel):
    name: str | None = None
    id: str | None = None
    tags: list[str] | None = None


class NetworkMode(StrEnum):
    NONE = "none"
    BRIDGE = "bridge"
    HOST = "host"


class ContainerImageHistoryEntry(BaseModel):
    """One line from Docker image history (docker API).

    Docker engine returns keys with specific casing; we accept them via aliases and
    normalize to snake_case on our JSON output.
    """

    id: str | None = Field(default=None, alias="Id")
    created: int | None = Field(default=None, alias="Created")
    created_by: str | None = Field(default=None, alias="CreatedBy")
    tags: list[str] | None = Field(default=None, alias="Tags")
    size: int | None = Field(default=None, alias="Size")
    comment: str | None = Field(default=None, alias="Comment")


class ContainerInfo(BaseModel):
    """JSON shape for the runtime container.info resource.

    Returned by the runtime/docker exec servers as a single JSON part in ReadResourceResult.
    """

    image: ContainerImageInfo | dict
    container_id: str | None = None
    binds: dict | list | None = None
    working_dir: str | None = None
    network_mode: str | None = None
    image_history: list[ContainerImageHistoryEntry] | None = None


class SimpleOk(BaseModel):
    """Minimal ack type for tools that just signal success."""

    ok: bool = True
