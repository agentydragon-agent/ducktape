from __future__ import annotations

# ruff: noqa: E402

"""Adapter-level item builders for production code.

These helpers construct only adapter items that production code is allowed to
create directly (not full ResponsesResult objects, and not reasoning items).
Reasoning items originate from the model and should never be synthesized in prod.
"""

from typing import Any

import pydantic_core

from .model import AssistantMessageOut, FunctionCallItem, OutputText


def make_item_tool_call(*, call_id: str, name: str, arguments: dict[str, Any]) -> FunctionCallItem:
    """Create a function call item with JSON-serialized arguments."""
    return FunctionCallItem(
        call_id=call_id, name=name, arguments=pydantic_core.to_json(arguments, fallback=str).decode("utf-8")
    )


def make_item_assistant_text(text: str) -> AssistantMessageOut:
    return AssistantMessageOut(parts=[OutputText(text=text)])


class ItemFactory:
    """Small helper for constructing adapter items with convenient call_id handling.

    Production-safe: creates only tool_call and assistant_text items. It does not
    fabricate reasoning items or full ResponsesResult objects.
    """

    def __init__(self, call_id_prefix: str = "bootstrap") -> None:
        self._i = 0
        self._prefix = call_id_prefix

    def next_call_id(self) -> str:
        self._i += 1
        return f"{self._prefix}:{self._i}"

    def tool_call(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> FunctionCallItem:
        cid = call_id or self.next_call_id()
        return make_item_tool_call(call_id=cid, name=name, arguments=arguments)

    def assistant_text(self, text: str) -> AssistantMessageOut:
        return make_item_assistant_text(text)
