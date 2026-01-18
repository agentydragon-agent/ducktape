"""Generic container agent for in-container agent loops.

Provides a simple agent loop that:
1. Calls OpenAI Responses API (via proxy)
2. Dispatches tool calls to registered tools
3. Exits when a tool signals completion

Does not depend on MCP/fastmcp - tools are registered directly as callables.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from pydantic import BaseModel

from openai_utils.json_schema import OpenAICompatibleSchema

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result from a tool invocation."""

    output: str
    should_exit: bool = False


@dataclass
class Tool:
    """A tool that can be called by the agent.

    Args:
        name: Tool name (must match what LLM calls)
        description: Description shown to LLM
        parameters: Pydantic model class for argument validation
        fn: Async function that takes validated args and returns ToolResult
    """

    name: str
    description: str
    parameters: type[BaseModel]
    fn: Callable[[BaseModel], Awaitable[ToolResult]]

    def to_schema(self) -> dict[str, Any]:
        """Convert to OpenAI tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters.model_json_schema(schema_generator=OpenAICompatibleSchema),
                "strict": True,
            },
        }


# Reminder sent when agent outputs text instead of using tools
TEXT_OUTPUT_REMINDER = (
    "You must use tools to complete your task. Do not output text directly. "
    "Use the available tools, then call the appropriate completion tool when done."
)


@dataclass
class ContainerAgent:
    """Simple agent loop for in-container use.

    Does not depend on MCP/fastmcp. Tools are registered directly.
    """

    tools: list[Tool]
    client: OpenAI
    model: str
    system_prompt: str
    _tool_map: dict[str, Tool] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._tool_map = {t.name: t for t in self.tools}

    async def run(self) -> int:
        """Run the agent loop.

        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        tool_schemas = [t.to_schema() for t in self.tools]
        messages: list[dict[str, Any]] = []

        while True:
            try:
                response = self.client.responses.create(
                    model=self.model,
                    input=messages if messages else self.system_prompt,
                    instructions=self.system_prompt if messages else None,
                    tools=tool_schemas,
                )
            except Exception as e:
                logger.error("LLM API error: %s", e)
                print(f"LLM API error: {e}", file=sys.stderr)
                return 1

            output_items = response.output if hasattr(response, "output") else []

            # Check for text output
            has_text_output = any(
                isinstance(content, ResponseOutputText) and content.text.strip()
                for item in output_items
                if isinstance(item, ResponseOutputMessage)
                for content in item.content
            )

            # Get function calls
            function_calls = [item for item in output_items if isinstance(item, ResponseFunctionToolCall)]

            if not function_calls:
                logger.warning("Agent produced no function calls")
                print("Warning: Agent stopped without completing task", file=sys.stderr)
                return 1

            # Add assistant message to conversation
            messages.append({"role": "assistant", "content": output_items})

            # Remind agent to use tools if it output text
            if has_text_output:
                messages.append({"role": "user", "content": TEXT_OUTPUT_REMINDER})

            # Execute function calls
            tool_results = []
            should_exit = False

            for fc in function_calls:
                tool = self._tool_map.get(fc.name)
                if tool is None:
                    output = f"Error: Unknown tool '{fc.name}'"
                else:
                    try:
                        args = json.loads(fc.arguments)
                        validated_args = tool.parameters.model_validate(args)
                        result = await tool.fn(validated_args)
                        output = result.output
                        if result.should_exit:
                            should_exit = True
                            logger.info("Tool %s requested exit", fc.name)
                    except json.JSONDecodeError as e:
                        output = f"Error: Invalid JSON arguments: {e}"
                    except Exception as e:
                        output = f"Error in {fc.name}: {e}"
                        logger.exception("Tool error: %s", fc.name)

                tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": output})

            messages.extend(tool_results)

            if should_exit:
                print("Task completed")
                return 0
