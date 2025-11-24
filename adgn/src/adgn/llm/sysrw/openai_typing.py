from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Any, cast

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessageToolCallParam
from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputRefusal, ResponseOutputText
from pydantic import TypeAdapter

# Union type for response content parts
ResponseContentPart = ResponseOutputText | ResponseOutputRefusal


class MessageRole(StrEnum):
    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"
    TOOL = "tool"
    FUNCTION = "function"
    DEVELOPER = "developer"


# DATA EXTRACTION: Work with validated models only
def response_message_role(message: ResponseOutputMessage) -> MessageRole:
    """Extract role from a ResponseOutputMessage."""
    role_str = cast(str, message.role)
    return MessageRole(role_str)


def chat_param_message_role(message: ChatCompletionMessageParam) -> MessageRole:
    """Extract role from a ChatCompletionMessageParam."""
    return MessageRole(message["role"])


def iter_resolved_text(parts: list[ResponseContentPart]) -> Iterator[str]:
    """Extract text from validated content parts."""
    for part in parts:
        if isinstance(part, ResponseOutputText) and part.text:
            yield part.text
        elif isinstance(part, ResponseOutputRefusal) and part.refusal:
            yield part.refusal


def chat_param_message_tool_calls(message: ChatCompletionMessageParam) -> list[ChatCompletionMessageToolCallParam]:
    """Extract tool calls from a ChatCompletionMessageParam."""
    # Only assistant messages can have tool_calls
    role = MessageRole(message["role"])

    match role:
        case MessageRole.ASSISTANT:
            # ChatCompletionAssistantMessageParam has tool_calls field
            tool_calls = message.get("tool_calls")
            if tool_calls is None:
                return []
            return TypeAdapter(list[ChatCompletionMessageToolCallParam]).validate_python(tool_calls)
        case MessageRole.USER | MessageRole.SYSTEM | MessageRole.TOOL | MessageRole.FUNCTION | MessageRole.DEVELOPER:
            # Other message types don't have tool_calls
            return []
        case _:
            raise ValueError(f"Unhandled MessageRole: {role}")


def response_message_content_as_text(message: ResponseOutputMessage) -> str:
    """Extract text content from a ResponseOutputMessage."""
    content = message.content
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    parts = TypeAdapter(list[ResponseContentPart]).validate_python(content)
    return "\n".join(iter_resolved_text(parts))


def chat_param_message_content_as_text(message: ChatCompletionMessageParam) -> str:
    """Extract text content from a ChatCompletionMessageParam."""
    role = MessageRole(message["role"])

    match role:
        case MessageRole.ASSISTANT:
            # ChatCompletionAssistantMessageParam - content is optional
            content = message.get("content")
            if isinstance(content, str):
                return content
            return str(content) if content else ""
        case MessageRole.USER:
            # ChatCompletionUserMessageParam - content is required
            content = message["content"]
            if isinstance(content, str):
                return content
            return str(content)
        case MessageRole.SYSTEM:
            # ChatCompletionSystemMessageParam - content is required
            content = message["content"]
            if isinstance(content, str):
                return content
            return str(content)
        case MessageRole.TOOL | MessageRole.FUNCTION | MessageRole.DEVELOPER:
            # Other message types - handle gracefully
            content = message.get("content")
            if isinstance(content, str):
                return content
            return str(content) if content else ""
        case _:
            raise ValueError(f"Unhandled MessageRole: {role}")


# Removed parse_tool_call and extract_*_tool_call_info - no longer needed since we work with typed objects directly


def parse_response_messages(messages: Any) -> list[ResponseOutputMessage] | None:
    """Parse messages into validated ResponseOutputMessage objects.

    NOTE: This function should not exist. Callers should type data correctly at source.
    If using OpenAI SDK, responses are already typed. If parsing raw JSON, parse to
    typed objects immediately at the read site, not here. This defers type safety to
    runtime instead of compile time.

    TODO: Audit all callers and remove this function. See specimen issue 039.

    Args:
        messages: Unvalidated external payload (typically from OpenAI API response).
                  Structured validation happens via TypeAdapter within function.

    Returns:
        Validated list of ResponseOutputMessage objects, or None if messages is falsy.
    """
    if not messages:
        return None
    return TypeAdapter(list[ResponseOutputMessage]).validate_python(messages)


def parse_chat_messages(messages: Any) -> list[ChatCompletionMessageParam] | None:
    """Parse messages into validated ChatCompletionMessageParam objects.

    NOTE: This function should not exist. Callers should type data correctly at source.
    If using OpenAI SDK, responses are already typed. If parsing raw JSON, parse to
    typed objects immediately at the read site, not here. This defers type safety to
    runtime instead of compile time.

    TODO: Audit all callers and remove this function. See specimen issue 039.

    Args:
        messages: Unvalidated external payload (typically from stored state or API).
                  Structured validation happens via TypeAdapter within function.

    Returns:
        Validated list of ChatCompletionMessageParam objects, or None if messages is falsy.
    """
    if not messages:
        return None
    return TypeAdapter(list[ChatCompletionMessageParam]).validate_python(messages)


def parse_response(response: dict[str, Any]) -> Response:
    """Parse response data into validated Response object."""
    return TypeAdapter(Response).validate_python(response)


def parse_tools_list(tools: Any) -> list[dict[str, Any]]:
    """Parse a list of tools into validated dicts.

    Args:
        tools: Unvalidated external payload (typically from API response or config).
               Structured validation happens via TypeAdapter within function.

    Returns:
        Validated list of tool definition dicts.
    """
    return TypeAdapter(list[dict[str, Any]]).validate_python(tools if tools else [])
