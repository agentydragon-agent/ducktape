"""Schema building utilities for prompt contexts.

Separated from util.py to avoid circular imports with models.
"""

from collections.abc import Iterable
from typing import Any

from compact_json import Formatter  # type: ignore[import-untyped]
from pydantic import BaseModel


def build_input_schemas_json(models: Iterable[type[BaseModel]]) -> dict[str, dict]:
    """Return {ModelName: model_json_schema()} for all given Pydantic models.

    This is passed wholesale to Jinja; templates choose which to render.
    """
    return {m.__name__: m.model_json_schema() for m in models}


def compact_json_serialize(value: Any, max_width: int = 100) -> str:
    """Serialize a value to compact JSON format.

    Args:
        value: Python object to serialize (dict, list, Pydantic model, etc.)
        max_width: Maximum line width before wrapping (default: 100)

    Returns:
        Compact JSON string with smart line wrapping

    Use this instead of json.dumps(indent=2) for more readable output in prompts.
    """
    formatter = Formatter(max_inline_length=max_width)
    return formatter.serialize(value)  # type: ignore[no-any-return]
