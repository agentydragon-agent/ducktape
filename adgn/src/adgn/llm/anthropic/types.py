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

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AnthropicMessageRole(str, Enum):
    """Message role enum.

    Corresponds to the 'role' field in anthropic.types.MessageParam.
    """

    USER = "user"
    ASSISTANT = "assistant"
    # Note: "system" is not a message role in Anthropic API - it's a separate parameter


class AnthropicTextBlock(BaseModel):
    """Text content block.

    Corresponds to anthropic.types.TextBlockParam TypedDict.
    """

    type: str = Field(default="text", pattern="^text$")
    text: str


class AnthropicToolUseBlock(BaseModel):
    """Tool use content block.

    Corresponds to anthropic.types.ToolUseBlockParam TypedDict.
    """

    type: str = Field(default="tool_use", pattern="^tool_use$")
    id: str
    name: str
    input: dict[str, Any]


class AnthropicToolResultBlock(BaseModel):
    """Tool result content block.

    Corresponds to anthropic.types.ToolResultBlockParam TypedDict.
    """

    type: str = Field(default="tool_result", pattern="^tool_result$")
    tool_use_id: str
    content: str | list[AnthropicTextBlock]
    is_error: bool = False


# Union type for content blocks (corresponds to ContentBlockParam)
AnthropicContentBlock = AnthropicTextBlock | AnthropicToolUseBlock | AnthropicToolResultBlock


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
