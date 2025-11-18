from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
import json
from typing import Annotated, Any, Literal, cast

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessageToolCallParam
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputRefusal,
    ResponseOutputText,
)
from pydantic import BaseModel, Field, TypeAdapter, model_validator

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


def parse_response_parts(content: Any) -> list[ResponseContentPart] | None:
    """Parse content into validated ResponseContentPart objects."""
    if content is None:
        return None
    return TypeAdapter(list[ResponseContentPart]).validate_python(content)


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
    parts = parse_response_parts(content)
    if parts:
        return "\n".join(iter_resolved_text(parts))
    return str(content)


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


# Removed parse_tool_call - no longer needed since we work with typed objects directly


def extract_chat_tool_call_info(call: ChatCompletionMessageToolCallParam) -> ToolCallInfo:
    """Extract structured info from ChatCompletionMessageToolCallParam."""
    # call is already a validated ChatCompletionMessageToolCallParam TypedDict
    function = call["function"]
    return ToolCallInfo(
        name=function.get("name"),
        arguments=function.get("arguments"),
        call_id=call["id"],
        tool_id=call["id"],
        status=None,  # Not in this model
        type=call["type"],
    )


def extract_response_tool_call_info(call: ResponseFunctionToolCall) -> ToolCallInfo:
    """Extract structured info from ResponseFunctionToolCall."""
    return ToolCallInfo(
        name=call.name,
        arguments=call.arguments,
        call_id=call.call_id,
        tool_id=call.id or call.call_id,
        status=call.status,
        type="function",
    )


def parse_response_messages(messages: Any) -> list[ResponseOutputMessage] | None:
    """Parse messages into validated ResponseOutputMessage objects."""
    if not messages:
        return None
    return TypeAdapter(list[ResponseOutputMessage]).validate_python(messages)


def dump_response_messages(messages: list[ResponseOutputMessage]) -> list[dict[str, Any]]:
    """Convert validated ResponseOutputMessage objects back to dict form."""
    return [msg.model_dump(by_alias=True) for msg in messages]


def dump_chat_messages(messages: list[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
    """Convert ChatCompletionMessageParam objects to dict form."""
    return [TypeAdapter(dict[str, Any]).validate_python(msg) for msg in messages]


def parse_chat_messages(messages: Any) -> list[ChatCompletionMessageParam] | None:
    """Parse messages into validated ChatCompletionMessageParam objects."""
    if not messages:
        return None
    return TypeAdapter(list[ChatCompletionMessageParam]).validate_python(messages)


# Remove this function - parse the data into the right type first instead of handling unions


def parse_response(response: dict[str, Any]) -> Response:
    """Parse response data into validated Response object."""
    return TypeAdapter(Response).validate_python(response)


def parse_tool_params(params: str | dict[str, Any]) -> dict[str, Any]:
    """Parse tool parameters into a dict."""
    if isinstance(params, str):
        parsed = json.loads(params)
        return TypeAdapter(dict[str, Any]).validate_python(parsed)
    return TypeAdapter(dict[str, Any]).validate_python(params)


def parse_tools_list(tools: Any) -> list[dict[str, Any]]:
    """Parse a list of tools into validated dicts."""
    return TypeAdapter(list[dict[str, Any]]).validate_python(tools if tools else [])


# RESPONSE PROCESSING: Work with proper Response models
def iter_tool_calls_from_response(response: Response) -> Iterator[ToolCallInfo]:
    """Extract tool call information from a validated Response.

    In Responses API, tool calls are separate output items, not message attributes.
    """
    if not response.output:
        return
    for item in response.output:
        if isinstance(item, ResponseFunctionToolCall):
            yield extract_response_tool_call_info(item)
