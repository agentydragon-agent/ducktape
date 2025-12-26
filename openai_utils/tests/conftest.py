"""Shared fixtures and models for OpenAI tests."""

import os
from pathlib import Path
from typing import Annotated, Literal

import openai
from pydantic import BaseModel, ConfigDict, Field
import pytest

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


# ========== Discriminated Union with Defaults on Discriminator ==========


class HttpServerSpec(BaseModel):
    """HTTP server spec with discriminator default."""

    type: Literal["http"] = "http"
    url: str
    headers: list[str] | None = None
    model_config = ConfigDict(extra="forbid")


class InprocServerSpec(BaseModel):
    """Inproc server spec with discriminator default."""

    type: Literal["inproc"] = "inproc"
    factory: str
    model_config = ConfigDict(extra="forbid")


class DiscriminatedUnionWithDefaults(BaseModel):
    """Discriminated union where discriminator fields have defaults.

    Tests whether OpenAI strict mode accepts discriminated unions when
    the discriminator field (type) has a default value and thus isn't in
    the required array.
    """

    server: Annotated[HttpServerSpec | InprocServerSpec, Field(discriminator="type")]
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


# ========== Live OpenAI fixtures ==========


@pytest.fixture(scope="session")
def live_openai_model() -> str:
    """Canonical model used for live OpenAI tests."""

    return "gpt-4o-mini"


@pytest.fixture(scope="session")
def require_openai_api_key():
    """Skip live tests unless OPENAI_API_KEY is set."""

    if "OPENAI_API_KEY" not in os.environ:
        pytest.skip("OPENAI_API_KEY not set")
    return os.environ["OPENAI_API_KEY"]


@pytest.fixture(scope="session")
async def live_async_openai(require_openai_api_key):
    """Session-scoped AsyncOpenAI client for live tests."""

    _ = require_openai_api_key
    return openai.AsyncOpenAI()
