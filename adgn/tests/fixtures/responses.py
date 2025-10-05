from __future__ import annotations

import os
from typing import Any

import pytest

from adgn.openai_utils import builders
from adgn.openai_utils.model import (
    AssistantMessageOut,
    FunctionCallItem,
    ReasoningItem,
    ResponsesResult,
    Usage,
)


@pytest.fixture(scope="session")
def reasoning_model() -> str:
    """Default reasoning-capable model for adapter fixtures.

    Tests may override via RESPONSES_TEST_MODEL env.
    """
    return os.environ.get("RESPONSES_TEST_MODEL", "gpt-5-nano")


class ResponsesFactory(builders.ItemFactory):
    """Convenience adapter response builders bound to a model name."""

    def __init__(self, model: str):
        super().__init__(call_id_prefix="test")
        self.model = model
        self._reasoning_seq = 0

    def _next_reasoning_id(self) -> int:
        self._reasoning_seq += 1
        return self._reasoning_seq

    def make_assistant_message(self, text: str) -> ResponsesResult:
        return ResponsesResult(
            id="resp_msg",
            usage=Usage(input_tokens=0, output_tokens=1, total_tokens=1),
            output=[self.assistant_text(text)],
        )

    def make_tool_call(
        self, name: str, arguments: dict | str, call_id: str | None = None
    ) -> ResponsesResult:
        return self.make(self.tool_call(name, arguments, call_id))

    # ---- Low-level item builders (compose with make(...items)) ----

    def make_item_reasoning(self, id: str | None = None) -> ReasoningItem:
        return ReasoningItem(id=id or f"rs_{self._next_reasoning_id()}")

    def make_item_tool_call_auto(self, name: str, arguments: dict | str) -> FunctionCallItem:
        return self.tool_call(name, arguments)

    # ---- Message/response constructors (compose items) ----

    def make(self, *items) -> ResponsesResult:
        # Minimal usage heuristic: count assistant text parts as output tokens >=1
        out_tokens = 0
        for it in items:
            if isinstance(it, AssistantMessageOut):
                out_tokens += max(1, len(it.text))
        usage = Usage(
            input_tokens=0,
            output_tokens=(1 if out_tokens else 0),
            total_tokens=(1 if out_tokens else 0),
        )
        # Coerce any plain dicts to proper models if needed (not expected here)
        return ResponsesResult(id="resp_generic", usage=usage, output=list(items))

    def make_tool_call_auto(self, name: str, arguments: dict | str) -> ResponsesResult:
        return self.make(self.make_item_tool_call_auto(name, arguments))

    def make_final_assistant(self, text: str) -> ResponsesResult:
        return self.make(self.assistant_text(text))

    def make_reasoning_then_assistant(self, text: str) -> ResponsesResult:
        return self.make(
            self.make_item_reasoning(),
            self.assistant_text(text),
        )

    def make_reasoning_tool_then_assistant(
        self, *, call_id: str, name: str, arguments: dict | str, text: str
    ) -> ResponsesResult:
        return self.make(
            self.make_item_reasoning(),
            self.tool_call(name, arguments, call_id),
            self.assistant_text(text),
        )

    def make_tool_call_with_output(
        self,
        name: str,
        arguments: dict | str,
        output: Any,
        call_id: str | None = None,
    ) -> ResponsesResult:
        call, tool_out = self.tool_call_with_output(
            name=name, arguments=arguments, output=output, call_id=call_id
        )
        return self.make(call, tool_out)


@pytest.fixture(scope="session")
def responses_factory(reasoning_model: str) -> ResponsesFactory:
    return ResponsesFactory(reasoning_model)
