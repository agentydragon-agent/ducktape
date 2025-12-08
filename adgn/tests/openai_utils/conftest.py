"""Shared fixtures for OpenAI strict mode tests.

This module contains common test models used across multiple strict mode test files
to avoid duplication while keeping tests clear and maintainable.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ========== Invalid Models (violate strict mode) ==========


class InvalidPathModel(BaseModel):
    """Invalid: uses Path type (generates format='path', not allowed in strict mode)."""

    path: Path
    model_config = ConfigDict(extra="forbid")


class InvalidSetModel(BaseModel):
    """Invalid: uses set type (generates uniqueItems, not allowed in strict mode)."""

    tags: set[str]
    model_config = ConfigDict(extra="forbid")


class MissingAdditionalPropertiesModel(BaseModel):
    """Invalid: missing extra='forbid' (additionalProperties: false required)."""

    name: str
    value: int
    # Intentionally no model_config with extra="forbid"


class NestedMissingAdditionalPropertiesModel(BaseModel):
    """Invalid: nested model missing additionalProperties."""

    class NestedModel(BaseModel):
        name: str
        # Intentionally no model_config

    nested: NestedModel
    model_config = ConfigDict(extra="forbid")


# ========== Discriminated Union Models ==========


class StringVariant(BaseModel):
    """String variant for discriminated unions."""

    kind: Literal["string"]
    value: str
    model_config = ConfigDict(extra="forbid")


class IntVariant(BaseModel):
    """Integer variant for discriminated unions."""

    kind: Literal["int"]
    value: int
    model_config = ConfigDict(extra="forbid")


class DiscriminatedUnionModel(BaseModel):
    """Model with discriminated union.

    Generates oneOf with Pydantic default generator (rejected by OpenAI).
    Generates anyOf with OpenAICompatibleSchema (accepted by OpenAI).
    """

    data: Annotated[StringVariant | IntVariant, Field(discriminator="kind")]
    model_config = ConfigDict(extra="forbid")


# ========== Valid Models (strict mode compliant) ==========


class SimpleValidModel(BaseModel):
    """Simple valid model with basic types and constraints."""

    name: str
    count: int = Field(ge=0, le=100)
    model_config = ConfigDict(extra="forbid")


class OptionalFieldModel(BaseModel):
    """Valid model with optional fields (anyOf with null is allowed)."""

    name: str
    optional_field: str | None = None
    model_config = ConfigDict(extra="forbid")


class SimpleUnionModel(BaseModel):
    """Valid model with simple union at property level (anyOf allowed)."""

    value: str | int
    model_config = ConfigDict(extra="forbid")


class NestedValidModel(BaseModel):
    """Valid nested model with all objects having additionalProperties."""

    class Inner(BaseModel):
        name: str
        model_config = ConfigDict(extra="forbid")

    nested: Inner
    model_config = ConfigDict(extra="forbid")
