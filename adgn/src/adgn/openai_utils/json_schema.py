"""Custom JSON schema generators for OpenAI strict mode compatibility.

Pydantic generates oneOf for discriminated unions, but OpenAI strict mode
doesn't support oneOf. This module provides a schema generator that converts
oneOf to anyOf while preserving discriminator metadata.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema


class OpenAICompatibleSchema(GenerateJsonSchema):
    """Generate OpenAI strict mode compatible JSON schemas.

    This schema generator modifies Pydantic's default behavior to be compatible
    with OpenAI's strict mode requirements:

    - Converts oneOf to anyOf for discriminated unions (oneOf not supported)
    - Preserves discriminator metadata for proper validation

    Usage:
        from adgn.openai_utils.json_schema import openai_json_schema

        # Recommended: use the helper function
        schema = openai_json_schema(MyModel)

        # Or explicitly pass the schema generator
        schema = MyModel.model_json_schema(schema_generator=OpenAICompatibleSchema)

        # Or with TypeAdapter:
        adapter = TypeAdapter(MyType)
        schema = adapter.json_schema(schema_generator=OpenAICompatibleSchema)

    Note: This only affects the JSON schema representation. Pydantic validation
    behavior is unchanged - discriminated union validation still works perfectly.
    """

    def tagged_union_schema(self, schema: core_schema.TaggedUnionSchema) -> JsonSchemaValue:
        """Override to generate anyOf instead of oneOf for discriminated unions.

        Pydantic generates oneOf for discriminated unions by default, which matches
        OpenAPI conventions but isn't supported by OpenAI strict mode. This converts
        it to anyOf while keeping all the discriminator metadata intact.
        """
        json_schema = super().tagged_union_schema(schema)

        # Convert oneOf to anyOf if present
        if "oneOf" in json_schema:
            json_schema["anyOf"] = json_schema.pop("oneOf")

        return json_schema


def openai_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Generate OpenAI-compatible JSON schema for a Pydantic model.

    This is a convenience wrapper around model_json_schema(schema_generator=OpenAICompatibleSchema)
    to avoid repetition throughout the codebase.

    Args:
        model: Pydantic BaseModel class to generate schema for

    Returns:
        JSON schema dict compatible with OpenAI structured outputs (anyOf instead of oneOf)
    """
    return model.model_json_schema(schema_generator=OpenAICompatibleSchema)
