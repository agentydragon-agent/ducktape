"""In-container agent loop for critic agents using agent_core.Agent.

Runs the full agent loop inside the container:
1. Fetches agent_run_id from environment
2. Constructs system prompt
3. Calls LLM via proxy (OPENAI_BASE_URL)
4. Executes tools (both shell exec and critic-specific tools)
5. Exits on successful submit or reported failure
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI
from pydantic import BaseModel

from agent_core.agent import Agent
from agent_core.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from agent_core.tool_provider import ToolResult, ToolSchema
from mcp_infra.exec.subprocess_exec import SubprocessExecArgs, run_exec
from openai_utils.json_schema import OpenAICompatibleSchema
from openai_utils.model import BoundOpenAIModel, SystemMessage
from props.core.agent_helpers import get_current_agent_run_id
from props.core.critic.tools import (
    DeleteIssueArgs,
    InsertIssueArgs,
    InsertOccurrenceArgs,
    ReportFailureArgs,
    SubmitArgs,
    delete_issue,
    insert_issue,
    insert_occurrence,
    list_issues,
    report_failure,
    submit,
)
from props.core.critic.tools import ToolResult as CriticToolResult
from props.core.db.session import get_session

logger = logging.getLogger(__name__)

# Reminder sent when agent outputs text instead of using tools
TEXT_OUTPUT_REMINDER = (
    "You must use tools to report issues. Do not output text directly. "
    "Use insert_issue and insert_occurrence to report issues, then call submit when done."
)

# Default workspace path
WORKSPACE = Path("/workspace")


@dataclass
class ExitState:
    """Tracks whether a tool has requested exit."""

    should_exit: bool = False


@dataclass
class CriticToolProvider:
    """Tool provider for critic agents with exec and critic-specific tools."""

    agent_run_id: UUID
    exit_state: ExitState = field(default_factory=ExitState)

    async def list_tools(self) -> list[ToolSchema]:
        """Return available tools."""
        # Exec tool schema
        exec_schema = ToolSchema(
            name="exec",
            description="Execute a shell command. Use for file operations, running tests, etc.",
            input_schema=SubprocessExecArgs.model_json_schema(schema_generator=OpenAICompatibleSchema),
        )

        # Critic tool schemas
        critic_schemas = [
            ToolSchema(
                name="insert_issue",
                description="Insert a reported issue. Call this before adding occurrences for the issue.",
                input_schema=_make_strict_schema(InsertIssueArgs),
            ),
            ToolSchema(
                name="insert_occurrence",
                description="Insert an occurrence for a reported issue. The issue must exist first. "
                "An occurrence can span multiple locations (e.g., duplicated code across files).",
                input_schema=_make_strict_schema(InsertOccurrenceArgs),
            ),
            ToolSchema(
                name="delete_issue",
                description="Delete a reported issue and all its occurrences. Use to remove incorrect issues.",
                input_schema=_make_strict_schema(DeleteIssueArgs),
            ),
            ToolSchema(
                name="list_issues",
                description="List all issues reported in this critique run. Returns JSON with issue IDs, rationales, and occurrence counts.",
                input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            ),
            ToolSchema(
                name="submit",
                description="Finalize and submit the critique. Validates all issues and marks the run as complete. Call this when done reviewing.",
                input_schema=_make_strict_schema(SubmitArgs),
            ),
            ToolSchema(
                name="report_failure",
                description="Report that the critique could not be completed due to blocking issues (e.g., no files in scope).",
                input_schema=_make_strict_schema(ReportFailureArgs),
            ),
        ]

        return [exec_schema] + critic_schemas

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool and return the result."""
        if name == "exec":
            return await self._call_exec(arguments)
        return self._call_critic_tool(name, arguments)

    async def _call_exec(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the exec tool."""
        try:
            exec_args = SubprocessExecArgs.model_validate(arguments)
            exec_result = await run_exec(exec_args, default_cwd=WORKSPACE)
            return ToolResult.json(exec_result.model_dump())
        except Exception as e:
            logger.exception("Exec tool error")
            return ToolResult.error(f"Error executing command: {e}")

    def _call_critic_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a critic tool and return the result."""
        try:
            result = self._dispatch_critic_tool(name, arguments)
            if result.should_exit:
                self.exit_state.should_exit = True
                logger.info("Tool %s requested exit", name)
            return ToolResult.text(result.output)
        except Exception as e:
            logger.exception("Critic tool error: %s", name)
            return ToolResult.error(f"Error in {name}: {e}")

    def _dispatch_critic_tool(self, name: str, arguments: dict[str, Any]) -> CriticToolResult:
        """Dispatch to the appropriate critic tool."""
        if name == "insert_issue":
            return insert_issue(self.agent_run_id, InsertIssueArgs.model_validate(arguments))
        if name == "insert_occurrence":
            return insert_occurrence(self.agent_run_id, InsertOccurrenceArgs.model_validate(arguments))
        if name == "delete_issue":
            return delete_issue(DeleteIssueArgs.model_validate(arguments))
        if name == "list_issues":
            return list_issues(self.agent_run_id)
        if name == "submit":
            return submit(self.agent_run_id, SubmitArgs.model_validate(arguments))
        if name == "report_failure":
            return report_failure(self.agent_run_id, ReportFailureArgs.model_validate(arguments))
        return CriticToolResult(output=f"Error: Unknown critic tool '{name}'")


def _make_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Generate OpenAI strict-compatible JSON schema from a Pydantic model."""
    schema = model.model_json_schema(schema_generator=OpenAICompatibleSchema)
    # Remove $defs as OpenAI strict mode doesn't support them at top level
    schema.pop("$defs", None)
    return schema


class LoggingHandler(BaseHandler):
    """Handler that logs events for debugging."""

    def on_error(self, exc: Exception) -> None:
        logger.error("Agent error: %s", exc)
        raise exc


async def run_critic_loop(system_prompt: str, model: str) -> int:
    """Run the critic agent loop.

    Args:
        system_prompt: The system prompt for the critic agent
        model: Model name (must match agent_run.model for proxy validation)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Get agent_run_id once at the start
    with get_session() as session:
        agent_run_id = get_current_agent_run_id(session)

    # Create tool provider with shared exit state
    tool_provider = CriticToolProvider(agent_run_id=agent_run_id)

    # Create OpenAI client pointing to proxy
    client = AsyncOpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    bound_model = BoundOpenAIModel(client=client, model=model)

    # Create handlers
    handlers: list[BaseHandler] = [
        LoggingHandler(),
        RedirectOnTextMessageHandler(TEXT_OUTPUT_REMINDER),
        AbortIf(lambda: tool_provider.exit_state.should_exit),
    ]

    # Create and run agent
    agent = await Agent.create(
        tool_provider=tool_provider,
        handlers=handlers,
        client=bound_model,
        parallel_tool_calls=False,  # Execute tools sequentially for clarity
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    # Add system prompt
    agent.process_message(SystemMessage.text(system_prompt))

    try:
        await agent.run()
        if tool_provider.exit_state.should_exit:
            print("Critique completed")
            return 0
        # Agent finished without explicit exit (shouldn't happen with proper abort handling)
        logger.warning("Agent finished without explicit exit")
        return 1
    except Exception as e:
        logger.error("Agent loop error: %s", e)
        return 1


def run_critic_loop_sync(system_prompt: str, model: str) -> int:
    """Synchronous wrapper for run_critic_loop."""
    return asyncio.run(run_critic_loop(system_prompt, model))
