from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


# Minimal, tolerant Pydantic models mirroring the shapes we care about
# when constructing next-turn Responses API input.
#
# Notes
# - We keep models permissive (extra="allow") to avoid breaking when the SDK
#   adds new fields.
# - We don't try to exactly match SDK output models; these are for test
#   assertions over our constructed input only.
# - Because assistant messages use role=..., and other items use type=...,
#   we cannot use a single discriminator across the whole union. Instead,
#   we provide a small helper to coerce dicts into one of the variants.


class ReasoningItem(BaseModel):
    type: Literal["reasoning"]
    id: str | None = None
    summary: list[dict[str, Any]] | None = None
    model_config = ConfigDict(extra="allow")


class FunctionCallItem(BaseModel):
    type: Literal["function_call"]
    name: str
    arguments: str | dict[str, Any] | list[Any] | None = None
    call_id: str | None = None
    model_config = ConfigDict(extra="allow")


class FunctionCallOutputItem(BaseModel):
    type: Literal["function_call_output"]
    call_id: str
    output: Any | None = None
    model_config = ConfigDict(extra="allow")


class AssistantMessageItem(BaseModel):
    role: Literal["assistant"]
    content: str | list[Any] | None = None
    model_config = ConfigDict(extra="allow")


class RawItem(BaseModel):
    """Fallback for items we don't explicitly model yet."""

    model_config = ConfigDict(extra="allow")


InputItem = (
    ReasoningItem
    | FunctionCallItem
    | FunctionCallOutputItem
    | AssistantMessageItem
    | RawItem
)


def coerce_input_item(obj: Any) -> InputItem:
    """Best-effort coercion of a dict-like input item to a typed model.

    Priority:
    - role == "assistant" -> AssistantMessageItem
    - type == "function_call_output" -> FunctionCallOutputItem
    - type == "function_call" -> FunctionCallItem
    - type == "reasoning" -> ReasoningItem
    - else -> RawItem
    """
    if not isinstance(obj, dict):
        return RawItem()

    if obj.get("role") == "assistant":
        return AssistantMessageItem.model_validate(obj)

    t = obj.get("type")
    if t == "function_call_output":
        return FunctionCallOutputItem.model_validate(obj)
    if t == "function_call":
        return FunctionCallItem.model_validate(obj)
    if t == "reasoning":
        return ReasoningItem.model_validate(obj)

    return RawItem.model_validate(obj)


def coerce_input_items(items: Any) -> list[InputItem]:
    if not isinstance(items, list):
        return []
    out: list[InputItem] = []
    for it in items:
        try:
            out.append(coerce_input_item(it))
        except Exception:
            out.append(RawItem())
    return out
