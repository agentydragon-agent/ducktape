from __future__ import annotations

import json
from dataclasses import dataclass
from functools import singledispatch
from typing import Any, Literal, Annotated, Protocol, Self, cast
from adgn.llm.openai_utils.retry import retry_decorator

from openai import AsyncOpenAI
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from openai.types.responses.response_reasoning_item import ResponseReasoningItem
from openai.types.shared_params import Reasoning as ReasoningParams
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ------------------------------
# Typed, tolerant input items we compose into Responses API "input"
# ------------------------------


class InputTextPart(BaseModel):
    type: Literal["input_text"] = "input_text"
    text: str
    model_config = ConfigDict(extra="allow")


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: list[InputTextPart] | None = None
    model_config = ConfigDict(extra="allow")

    @classmethod
    def text(cls, text: str) -> Self:
        return cls(content=[InputTextPart(text=text)])


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: list[InputTextPart]
    model_config = ConfigDict(extra="allow")

    @classmethod
    def text(cls, text: str) -> Self:
        return cls(content=[InputTextPart(text=text)])


class SystemMessage(BaseModel):
    role: Literal["system"] = "system"
    content: list[InputTextPart]
    model_config = ConfigDict(extra="allow")

    @classmethod
    def text(cls, text: str) -> Self:
        return cls(content=[InputTextPart(text=text)])


class ReasoningItem(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    id: str | None = None
    model_config = ConfigDict(extra="allow")


class FunctionCallItem(BaseModel):
    type: Literal["function_call"] = "function_call"
    name: str
    arguments: str | dict[str, object] | list[object] | None = None
    call_id: str | None = None
    model_config = ConfigDict(extra="allow")


class FunctionCallOutputItem(BaseModel):
    # Responses API prefers the payload under "output".
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: object | None = Field(
        default=None, description="Structured payload returned from the tool"
    )
    model_config = ConfigDict(extra="allow")


InputItem = (
    AssistantMessage
    | UserMessage
    | SystemMessage
    | ReasoningItem
    | FunctionCallItem
    | FunctionCallOutputItem
)


class ToolChoiceFunction(BaseModel):
    type: Literal["function"] = "function"
    name: str
    model_config = ConfigDict(extra="allow")


ToolChoice = Literal["auto", "required"] | ToolChoiceFunction


class ResponsesRequest(BaseModel):
    """Thin, tolerant request model for OpenAI Responses API calls we make."""

    input: list[InputItem] | str

    # Common options we actually use; others are passed through (extra=allow)
    instructions: str | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: ToolChoice | None = None
    parallel_tool_calls: bool | None = None
    stream: bool = False
    store: bool | None = None
    reasoning: ReasoningParams | None = None
    max_output_tokens: int | None = None

    # Allow unknown fields for forward-compat (timeouts, metadata, etc.)
    model_config = ConfigDict(extra="allow")

    def to_kwargs(self) -> dict[str, Any]:
        """Normalize to kwargs compatible with AsyncOpenAI.responses.create()."""

        def norm_item(x: Any) -> Any:
            if isinstance(x, BaseModel):
                d = x.model_dump(exclude_none=True)
                return d
            return x

        payload = self.model_dump(exclude_none=True)
        if isinstance(payload.get("input"), list):
            payload["input"] = [norm_item(it) for it in payload["input"]]  # type: ignore[index]
        return payload


# ------------------------------
# Structured response types (our layer)
# ------------------------------


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ReasoningOut(BaseModel):
    kind: Literal["reasoning"] = "reasoning"
    id: str | None = None

    def to_input_item(self) -> ReasoningItem:
        return ReasoningItem(id=self.id)

    @classmethod
    def from_input_item(cls, item: ReasoningItem) -> ReasoningOut:
        return cls(id=item.id)


class FunctionCallOut(BaseModel):
    kind: Literal["function_call"] = "function_call"
    name: str
    arguments: str | None = None
    call_id: str

    def to_input_item(self) -> FunctionCallItem:
        return FunctionCallItem(
            name=self.name, arguments=self.arguments, call_id=self.call_id
        )

    @staticmethod
    def _stringify_arguments(
        args: str | dict[str, object] | list[object] | None,
    ) -> str | None:
        if args is None:
            return None
        if isinstance(args, str):
            return args
        try:
            return json.dumps(args)
        except TypeError:
            return str(args)

    @classmethod
    def from_input_item(cls, item: FunctionCallItem) -> FunctionCallOut:
        if item.call_id is None:
            raise ValueError("FunctionCallItem missing call_id")
        return cls(
            name=item.name,
            call_id=item.call_id,
            arguments=cls._stringify_arguments(item.arguments),
        )


class FunctionCallOutputOut(BaseModel):
    kind: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str

    def to_input_item(self) -> FunctionCallOutputItem:
        return FunctionCallOutputItem(call_id=self.call_id, output=self.output)

    @classmethod
    def from_input_item(cls, item: FunctionCallOutputItem) -> FunctionCallOutputOut:
        output = item.output
        if output is None:
            return cls(call_id=item.call_id, output="")
        if isinstance(output, str):
            return cls(call_id=item.call_id, output=output)
        try:
            return cls(call_id=item.call_id, output=json.dumps(output))
        except TypeError:
            return cls(call_id=item.call_id, output=str(output))


class AssistantMessagePart(BaseModel):
    text: str
    annotations: list[dict[str, Any]] | None = None
    model_config = ConfigDict(extra="allow")


class AssistantResponseMessage(BaseModel):
    kind: Literal["assistant_text"] = "assistant_text"
    parts: list[AssistantMessagePart]
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_text(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"parts": [{"text": data}]}
        if isinstance(data, dict):
            if "parts" not in data:
                text = data.get("text")
                if isinstance(text, str):
                    new_data = dict(data)
                    new_data.pop("text", None)
                    new_data["parts"] = [{"text": text}]
                    return new_data
        return data

    @property
    def text(self) -> str:
        return "\n".join(part.text for part in self.parts if part.text)

    def to_input_item(self) -> AssistantMessage:
        content_parts: list[InputTextPart] = []
        for part in self.parts:
            part_data = part.model_dump(exclude_none=True)
            part_data.setdefault("type", "input_text")
            content_parts.append(InputTextPart.model_validate(part_data))
        return AssistantMessage(role="assistant", content=content_parts)

    @classmethod
    def from_input_item(cls, item: AssistantMessage) -> AssistantResponseMessage:
        parts: list[AssistantMessagePart] = []
        for block in item.content or []:
            if isinstance(block, InputTextPart):
                parts.append(
                    AssistantMessagePart.model_validate(
                        block.model_dump(exclude_none=True)
                    )
                )
        return cls(parts=parts)


ResponseOutItem = Annotated[
    ReasoningOut | FunctionCallOut | AssistantResponseMessage,
    Field(discriminator="kind"),
]


@singledispatch
def response_out_item_to_input(item: BaseModel) -> InputItem:
    raise TypeError(f"Unsupported response item type: {type(item)!r}")


@response_out_item_to_input.register
def _(item: ReasoningOut) -> InputItem:
    return item.to_input_item()


@response_out_item_to_input.register
def _(item: FunctionCallOut) -> InputItem:
    return item.to_input_item()


@response_out_item_to_input.register
def _(item: AssistantResponseMessage) -> InputItem:
    return item.to_input_item()


def _message_output_to_assistant(
    message: ResponseOutputMessage,
) -> AssistantResponseMessage | None:
    parts: list[AssistantMessagePart] = []
    for content_item in message.content:
        if isinstance(content_item, ResponseOutputText):
            part = AssistantMessagePart(
                text=content_item.text,
                annotations=[
                    annotation.model_dump(exclude_none=True)
                    for annotation in content_item.annotations
                ]
                if content_item.annotations
                else None,
            )
            parts.append(part)
    if not parts:
        return None
    return AssistantResponseMessage(parts=parts)


class ResponsesResult(BaseModel):
    id: str
    usage: Usage
    output: list[ResponseOutItem]

    def to_input_items(self) -> list[InputItem]:
        return [response_out_item_to_input(item) for item in self.output]


def convert_sdk_response(sdk_resp: Response) -> ResponsesResult:
    """Convert an OpenAI SDK Response to our typed ResponsesResult.

    Mirrors OpenAIModel.responses_create conversion so non-Pydantic clients
    (that accept kwargs) can still be used with MiniCodex.
    """
    out_items: list[ResponseOutItem] = []
    for item in sdk_resp.output:
        if isinstance(item, ResponseReasoningItem):
            out_items.append(ReasoningOut(id=item.id))
        elif isinstance(item, ResponseFunctionToolCall):
            out_items.append(
                FunctionCallOut(
                    name=item.name, arguments=item.arguments, call_id=item.call_id
                )
            )
        elif isinstance(item, ResponseOutputMessage):
            converted = _message_output_to_assistant(item)
            if converted is not None:
                out_items.append(converted)
        else:
            continue
    u = sdk_resp.usage
    if u is None:
        usage = Usage(input_tokens=0, output_tokens=0, total_tokens=0)
    else:
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            total_tokens=u.total_tokens,
        )
    return ResponsesResult(id=sdk_resp.id, usage=usage, output=out_items)


# ------------------------------
# Thin wrapper used in prod/tests
# ------------------------------


@dataclass
class OpenAIModel:
    client: AsyncOpenAI

    @property
    def responses(self):  # Pydantic-only surface: .responses.create(ResponsesRequest)
        outer = self

        class _Compat:
            async def create(self, req: ResponsesRequest) -> ResponsesResult:
                result = await outer.responses_create(req)
                return cast(ResponsesResult, result)

        return _Compat()

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        """Create a Responses completion (non-streaming) and convert to our types."""
        if not isinstance(req, ResponsesRequest):
            raise TypeError("responses_create expects a ResponsesRequest instance")
        # No baked-in defaults; caller must set model/tool_choice/reasoning explicitly

        kwargs = req.to_kwargs()
        sdk_resp: Response = await self.client.responses.create(**kwargs)
        # Convert SDK response to our typed ResponsesResult
        out_items: list[ResponseOutItem] = []
        for item in sdk_resp.output:
            if isinstance(item, ResponseReasoningItem):
                out_items.append(ReasoningOut(id=item.id))
            elif isinstance(item, ResponseFunctionToolCall):
                out_items.append(
                    FunctionCallOut(
                        name=item.name, arguments=item.arguments, call_id=item.call_id
                    )
                )
            elif isinstance(item, ResponseOutputMessage):
                converted = _message_output_to_assistant(item)
                if converted is not None:
                    out_items.append(converted)
            else:
                continue
        u = sdk_resp.usage
        if u is None:
            usage = Usage(input_tokens=0, output_tokens=0, total_tokens=0)
        else:
            usage = Usage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                total_tokens=u.total_tokens,
            )
        return ResponsesResult(id=sdk_resp.id, usage=usage, output=out_items)


# ------------------------------
# Test-friendly fake (records typed CapturedRequest, returns canned outputs)
# ------------------------------


@dataclass
class RetryingOpenAIModel:
    """Retry-decorated wrapper around an OpenAIModel (our Pydantic interface)."""

    base: OpenAIModel

    @retry_decorator()
    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        result = await self.base.responses_create(req)
        return cast(ResponsesResult, result)


@dataclass
class BoundOpenAIModel:
    """AsyncOpenAI adapter that binds a specific model and returns Pydantic results.

    Implements the OpenAIModelProto protocol.
    """

    client: AsyncOpenAI
    model: str
    reasoning_effort: str | None = None

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        kwargs = req.to_kwargs()
        if "model" not in kwargs:
            kwargs["model"] = self.model
        if self.reasoning_effort and "reasoning" not in kwargs:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        sdk_resp: Response = await self.client.responses.create(**kwargs)
        return convert_sdk_response(sdk_resp)


# ---------------------------------------------
# Protocol for MiniCodex consumption (bound model)
# ---------------------------------------------


class OpenAIModelProto(Protocol):  # pragma: no cover - structural typing only
    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult: ...


class FakeOpenAIModel:
    def __init__(
        self, outputs: list[ResponsesResult] | tuple[ResponsesResult, ...]
    ) -> None:
        self._outputs = list(outputs)
        self.calls = 0
        self.captured: list[ResponsesRequest] = []

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        if not isinstance(req, ResponsesRequest):
            raise TypeError("responses_create expects a ResponsesRequest instance")
        self.captured.append(req.model_copy(deep=True))
        idx = min(self.calls, len(self._outputs) - 1) if self._outputs else 0
        self.calls += 1
        return self._outputs[idx]
