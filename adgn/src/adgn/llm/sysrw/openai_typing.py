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
type ResponseContentPart = ResponseOutputText | ResponseOutputRefusal


class MessageRole(StrEnum):
    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"
    TOOL = "tool"
    FUNCTION = "function"
    DEVELOPER = "developer"


class ToolCallInfo(BaseModel):
    """Structured tool call information extracted from responses."""

    name: str | None
    arguments: str | None
    call_id: str | None
    tool_id: str | None
    status: str | None
    type: str | None


class StandardUserMessage(BaseModel):
    type: Literal["user"] = "user"
    role: MessageRole = MessageRole.USER
    content: str


class StandardSystemMessage(BaseModel):
    type: Literal["system"] = "system"
    role: MessageRole = MessageRole.SYSTEM
    content: str


class StandardAssistantMessage(BaseModel):
    type: Literal["assistant"] = "assistant"
    role: MessageRole = MessageRole.ASSISTANT
    content: str | None = None
    tool_calls: list[ToolCallInfo] = []

    @model_validator(mode="after")
    def validate_not_empty(self) -> StandardAssistantMessage:
        if self.content is None and not self.tool_calls:
            raise ValueError("Assistant message must have content or tool_calls")
        return self


class StandardAssistantRefusal(BaseModel):
    type: Literal["refusal"] = "refusal"
    role: MessageRole = MessageRole.ASSISTANT
    refusal: str


class StandardToolMessage(BaseModel):
    type: Literal["tool"] = "tool"
    role: MessageRole = MessageRole.TOOL
    content: str
    tool_call_id: str


class StandardFunctionMessage(BaseModel):
    type: Literal["function"] = "function"
    role: MessageRole = MessageRole.FUNCTION
    content: str
    name: str


StandardMessage = Annotated[
    StandardUserMessage
    | StandardSystemMessage
    | StandardAssistantMessage
    | StandardAssistantRefusal
    | StandardToolMessage
    | StandardFunctionMessage,
    Field(discriminator="type"),
]


def chat_param_to_standard_message(msg: ChatCompletionMessageParam) -> StandardMessage:
    """Convert ChatCompletionMessageParam to StandardMessage."""
    role = chat_param_message_role(msg)

    match role:
        case MessageRole.USER:
            return StandardUserMessage(content=chat_param_message_content_as_text(msg))
        case MessageRole.SYSTEM:
            return StandardSystemMessage(content=chat_param_message_content_as_text(msg))
        case MessageRole.ASSISTANT:
            # Check for refusal first (only assistant messages can have refusal)
            refusal = msg.get("refusal")
            if refusal and isinstance(refusal, str):
                return StandardAssistantRefusal(refusal=refusal)

            content_text = chat_param_message_content_as_text(msg)
            content = content_text if content_text else None
            tool_calls = [extract_chat_tool_call_info(call) for call in chat_param_message_tool_calls(msg)]

            # Handle legacy function_call (convert to tool call, only for assistant)
            function_call = msg.get("function_call")
            if function_call and isinstance(function_call, dict):
                name = function_call.get("name")
                arguments = function_call.get("arguments")
                tool_calls.append(
                    ToolCallInfo(
                        name=name if isinstance(name, str) else None,
                        arguments=arguments if isinstance(arguments, str) else None,
                        call_id=None,  # Legacy function calls don't have IDs
                        tool_id=None,
                        status=None,
                        type="function",
                    )
                )

            return StandardAssistantMessage(content=content, tool_calls=tool_calls)
        case MessageRole.TOOL:
            tool_call_id = msg.get("tool_call_id")
            tool_call_id_str = tool_call_id if isinstance(tool_call_id, str) else ""
            return StandardToolMessage(content=chat_param_message_content_as_text(msg), tool_call_id=tool_call_id_str)
        case MessageRole.FUNCTION:
            name = msg.get("name")
            name_str = name if isinstance(name, str) else ""
            return StandardFunctionMessage(content=chat_param_message_content_as_text(msg), name=name_str)
        case _:
            raise ValueError(f"Unhandled MessageRole: {role}")


# DATA EXTRACTION: Work with validated models only
def response_message_role(message: ResponseOutputMessage) -> MessageRole:
    """Extract role from a ResponseOutputMessage."""
    role_str = cast(str, message.role)
    return MessageRole(role_str)


def chat_param_message_role(message: ChatCompletionMessageParam) -> MessageRole:
    """Extract role from a ChatCompletionMessageParam."""
    role_str = message["role"]
    try:
        return MessageRole(role_str)
    except ValueError as e:
        raise ValueError(f"Unknown ChatCompletionMessageParam role: {role_str}") from e


def message_content(message: ResponseOutputMessage) -> Any:
    """Extract content from a validated ResponseOutputMessage."""
    return message.content


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
    try:
        role = MessageRole(message["role"])
    except ValueError as e:
        raise ValueError(f"Unknown ChatCompletionMessageParam role: {message['role']}") from e

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
    try:
        role = MessageRole(message["role"])
    except ValueError as e:
        raise ValueError(f"Unknown ChatCompletionMessageParam role: {message['role']}") from e

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
