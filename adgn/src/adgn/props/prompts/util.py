from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel


def _to_json_filter(value: Any, indent: int = 2) -> str:
    """Jinja filter to serialize Pydantic models/lists to JSON."""
    if isinstance(value, list) and value and isinstance(value[0], BaseModel):
        return json.dumps([item.model_dump(mode="json") for item in value], ensure_ascii=False, indent=indent)
    if isinstance(value, BaseModel):
        return value.model_dump_json(indent=indent)
    return json.dumps(value, ensure_ascii=False, indent=indent)


def get_templates_env() -> Environment:
    """Load prompt templates from the installed package using importlib.resources.

    Templates live under the adgn.props.prompts package directory.
    """
    env = Environment(
        loader=PackageLoader("adgn.props", "prompts"),
        autoescape=select_autoescape(["md", "markdown", "txt", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["to_json"] = _to_json_filter
    return env


def render_prompt_template(name: str, **ctx: object) -> str:
    env = get_templates_env()
    tmpl = env.get_template(name)
    return str(tmpl.render(**ctx)).strip()


def build_input_schemas_json(models: Iterable[type[BaseModel]]) -> dict[str, dict]:
    """Return {ModelName: model_json_schema()} for all given Pydantic models.

    This is passed wholesale to Jinja; templates choose which to render.
    """
    out: dict[str, dict] = {}
    for m in models:
        out[m.__name__] = m.model_json_schema()
    return out


def build_scope_text(include: list[str], exclude: list[str] | None = None) -> str:
    """Human-readable scope string used in prompt headers.

    Example: "all files under wt/** (excluding: wt/tests/**)"
    """
    inc = ", ".join(include)
    if exclude:
        return f"all files under {inc} (excluding: {', '.join(exclude)})"
    return f"all files under {inc}"
