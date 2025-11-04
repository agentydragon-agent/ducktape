from __future__ import annotations

from collections.abc import Iterator
from typing import Any, TypeAlias

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
)
from openai.types.responses import (
    Response,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
)
from pydantic import BaseModel, TypeAdapter

# Union type for response content parts
ResponseContentPart: TypeAlias = ResponseOutputText | ResponseOutputRefusal


class ToolCallInfo(BaseModel):
    """Structured tool call information extracted from responses."""

    name: str | None
    arguments: str | None
    call_id: str | None
    tool_id: str | None
    status: str | None
    type: str | None


# DATA EXTRACTION: Work with validated models only
def message_role(message: ResponseOutputMessage | ChatCompletionMessageParam) -> str:
    """Extract role from a validated message."""
    return message.role.lower() if message.role else ""


def message_content(message: ResponseOutputMessage | ChatCompletionMessageParam) -> Any:
    """Extract content from a validated message."""
    return message.content


def message_content_as_text(message: ResponseOutputMessage | ChatCompletionMessageParam) -> str:
    """Extract text content from a validated message."""
    content = message.content
    if isinstance(content, str):
        return content

    if content is None:
        return ""

    try:
        parts = TypeAdapter(list[ResponseContentPart]).validate_python(content)
        return "\n".join(_extract_text_from_parts(parts))
    except Exception:
        return str(content)


def tool_call_arguments(call: ChatCompletionMessageToolCallParam) -> str:
    """Extract arguments from a validated tool call."""
    if not call.function or not call.function.arguments:
        return ""
    return str(call.function.arguments)


def extract_tool_call_info(tool_call: ChatCompletionMessageToolCallParam) -> ToolCallInfo:
    """Extract structured info from a validated tool call."""
    return ToolCallInfo(
        name=tool_call.function.name if tool_call.function else None,
        arguments=tool_call.function.arguments if tool_call.function else None,
        call_id=tool_call.id,
        tool_id=tool_call.id,
        status=None,  # Not in this model
        type=tool_call.type,
    )


# RESPONSE PROCESSING: Work with proper Response models
def iter_tool_calls_from_response(response: Response) -> Iterator[ToolCallInfo]:
    """Extract tool call information from a validated Response."""
    if not response.output:
        return
    for item in response.output:
        # Handle ResponseOutputMessage items that might contain tool calls
        if hasattr(item, "tool_calls") and item.tool_calls:
            tool_calls = TypeAdapter(list[ChatCompletionMessageToolCallParam]).validate_python(
                item.tool_calls
            )
            for tool_call in tool_calls:
                yield extract_tool_call_info(tool_call)


# PRIVATE HELPERS
def _extract_text_from_parts(parts: list[ResponseContentPart]) -> Iterator[str]:
    """Extract text from validated content parts."""
    for part in parts:
        if isinstance(part, ResponseOutputText) and part.text:
            yield part.text
        elif isinstance(part, ResponseOutputRefusal) and part.refusal:
            yield part.refusal
