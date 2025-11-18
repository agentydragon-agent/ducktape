"""Translation between Anthropic and OpenAI message formats."""

from __future__ import annotations

import json
from typing import Any

from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.responses import ResponseOutputMessage

from adgn.llm.anthropic.types import (
    Message as AnthropicMessage,
    MessageRole as AnthropicMessageRole,
    TextBlock as AnthropicTextBlock,
    ToolResultBlock as AnthropicToolResultBlock,
    ToolUseBlock as AnthropicToolUseBlock,
)

from adgn.llm.anthropic.text_extraction import extract_text_content

from .openai_typing import dump_response_messages, parse_response_messages


def anthropic_to_chat_messages(
    messages: list[AnthropicMessage], system: str | None = None
) -> list[ChatCompletionMessageParam]:
    """Translate Anthropic messages into OpenAI Chat Completion format."""
    result: list[ChatCompletionMessageParam] = []
    if system:
        result.append(ChatCompletionSystemMessageParam(role="system", content=system))

    for message in messages:
        if isinstance(message.content, str):
            if message.content.strip():
                if message.role == AnthropicMessageRole.USER:
                    result.append(ChatCompletionUserMessageParam(role="user", content=message.content))
                elif message.role == AnthropicMessageRole.ASSISTANT:
                    result.append(ChatCompletionAssistantMessageParam(role="assistant", content=message.content))
            continue

        # message.content is list[ContentBlock] - Pydantic models
        content_blocks = message.content

        if message.role == AnthropicMessageRole.ASSISTANT:
            text_buf: list[str] = []
            tool_calls: list[ChatCompletionMessageToolCallParam] = []
            for block in content_blocks:
                if isinstance(block, AnthropicTextBlock):
                    text_buf.append(block.text)
                elif isinstance(block, AnthropicToolUseBlock):
                    args_str = json.dumps(block.input, ensure_ascii=False, separators=(",", ":"))
                    tool_call = ChatCompletionMessageToolCallParam(
                        type="function",
                        function={"name": block.name, "arguments": args_str},
                        id=block.id,
                    )
                    tool_calls.append(tool_call)
            if text_buf or tool_calls:
                content = "\n".join(text_buf) if text_buf else None
                if tool_calls:
                    result.append(
                        ChatCompletionAssistantMessageParam(
                            role="assistant", content=content, tool_calls=tool_calls
                        )
                    )
                elif content:
                    result.append(ChatCompletionAssistantMessageParam(role="assistant", content=content))

        elif message.role == AnthropicMessageRole.USER:
            text_parts: list[str] = []
            tool_msgs: list[ChatCompletionToolMessageParam] = []
            for block in content_blocks:
                if isinstance(block, AnthropicTextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, AnthropicToolResultBlock):
                    if isinstance(block.content, str):
                        tool_text = block.content
                    else:
                        # list[TextBlock]
                        tool_text = "\n".join(b.text for b in block.content)
                    tool_msgs.append(
                        ChatCompletionToolMessageParam(
                            role="tool", tool_call_id=block.tool_use_id, content=tool_text
                        )
                    )
            result.extend(tool_msgs)
            if text_parts:
                result.append(ChatCompletionUserMessageParam(role="user", content="\n".join(text_parts)))

    return result


def anthropic_to_responses_input(
    messages: list[AnthropicMessage], system: str | None = None
) -> list[ResponseOutputMessage]:
    """Translate Anthropic messages into OpenAI Responses API input format."""

    def _join_text_content(content: str | list[Any]) -> str:
        if isinstance(content, str):
            return content
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "\n".join(texts)

    raw_messages: list[dict[str, Any]] = []
    if system:
        raw_messages.append({"role": "system", "content": [{"type": "input_text", "text": system}]})

    for msg in messages:
        if msg.role not in (AnthropicMessageRole.USER, AnthropicMessageRole.ASSISTANT):
            continue

        text = _join_text_content(msg.content) if isinstance(msg.content, list) else msg.content
        if text.strip():
            raw_messages.append({"role": msg.role.value, "content": [{"type": "input_text", "text": text}]})

    validated = parse_response_messages(raw_messages)
    if validated is None:
        return []
    return validated


def anthropic_messages_to_standard(messages: list[AnthropicMessage]) -> list[ChatCompletionMessageParam]:
    """Convert Anthropic messages to ChatCompletionMessageParam for grader context.

    Only extracts text content, suitable for grader context where tool calls are not needed.
    """
    result: list[ChatCompletionMessageParam] = []
    for msg in messages:
        text_content = extract_text_content(msg).strip()
        if not text_content:
            continue

        if msg.role == AnthropicMessageRole.USER:
            result.append(ChatCompletionUserMessageParam(role="user", content=text_content))
        elif msg.role == AnthropicMessageRole.ASSISTANT:
            result.append(ChatCompletionAssistantMessageParam(role="assistant", content=text_content))

    return result
