"""Schema building utilities for prompt contexts.

Separated from util.py to avoid circular imports with models.
"""

from collections.abc import Iterable

from pydantic import BaseModel


def build_input_schemas_json(models: Iterable[type[BaseModel]]) -> dict[str, dict]:
    """Return {ModelName: model_json_schema()} for all given Pydantic models.

    This is passed wholesale to Jinja; templates choose which to render.
    """
    return {m.__name__: m.model_json_schema() for m in models}
