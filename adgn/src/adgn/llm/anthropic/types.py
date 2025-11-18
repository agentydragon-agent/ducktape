"""Pydantic models for Anthropic Messages API types.

These are stronger-typed wrappers around Anthropic SDK's TypedDict types.
Anthropic SDK types are runtime dicts; these are Pydantic BaseModels with validation.

Corresponds to:
- anthropic.types.MessageParam (TypedDict)
- anthropic.types.ContentBlockParam (TypedDict union)
- anthropic.types.TextBlockParam (TypedDict)
- anthropic.types.ToolUseBlockParam (TypedDict)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class AnthropicMessageRole(StrEnum):
    """Message role enum.

    Corresponds to the 'role' field in anthropic.types.MessageParam.
    """

    USER = "user"
    ASSISTANT = "assistant"
    # Note: "system" is not a message role in Anthropic API - it's a separate parameter


class AnthropicTextBlock(BaseModel):
    """Text content block. Corresponds to anthropic.types.TextBlockParam."""

    type: Literal["text"] = "text"
    text: str


class AnthropicToolUseBlock(BaseModel):
    """Tool use content block. Corresponds to anthropic.types.ToolUseBlockParam."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class AnthropicToolResultBlock(BaseModel):
    """Tool result content block. Corresponds to anthropic.types.ToolResultBlockParam."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | list[AnthropicTextBlock]
    is_error: bool = False


# Discriminated union for content blocks (corresponds to ContentBlockParam)
AnthropicContentBlock = Annotated[
    AnthropicTextBlock | AnthropicToolUseBlock | AnthropicToolResultBlock,
    Field(discriminator="type"),
]


class AnthropicMessage(BaseModel):
    """A message in the Anthropic Messages API format.

    Pydantic wrapper for anthropic.types.MessageParam TypedDict.
    Provides runtime validation and proper attribute access instead of dict.get().

    Usage:
        msg = AnthropicMessage(role=AnthropicMessageRole.USER, content="Hello")
        assert msg.role == AnthropicMessageRole.USER  # Attribute access, not .get()

    Anthropic SDK equivalent (TypedDict):
        msg: MessageParam = {"role": "user", "content": "Hello"}
        role = msg.get("role")  # Dict access with .get()
    """

    role: AnthropicMessageRole
    content: str | list[AnthropicContentBlock]

    @property
    def text_content(self) -> str:
        """Extract all text content from the message, joining multiple blocks."""
        if isinstance(self.content, str):
            return self.content

        texts: list[str] = []
        for block in self.content:
            if isinstance(block, AnthropicTextBlock):
                texts.append(block.text)
        return "\n".join(texts)
