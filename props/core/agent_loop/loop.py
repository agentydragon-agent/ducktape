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
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from openai import AsyncOpenAI

from agent_core.agent import Agent
from agent_core.direct_provider import DirectToolProvider
from agent_core.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler
from agent_core.loop_control import AllowAnyToolOrTextMessage
from mcp_infra.exec.models import BaseExecResult
from mcp_infra.exec.subprocess_exec import SubprocessExecArgs, run_exec
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


def create_critic_tool_provider(agent_run_id: UUID, exit_state: ExitState) -> DirectToolProvider:
    """Create a tool provider with critic tools bound to the given agent run."""
    provider = DirectToolProvider()

    @provider.tool
    async def exec(args: SubprocessExecArgs) -> BaseExecResult:
        """Execute a shell command. Use for file operations, running tests, etc."""
        return await run_exec(args, default_cwd=WORKSPACE)

    @provider.tool(name="insert_issue")
    def insert_issue_impl(args: InsertIssueArgs) -> str:
        """Insert a reported issue. Call this before adding occurrences for the issue."""
        return insert_issue(agent_run_id, args)

    @provider.tool(name="insert_occurrence")
    def insert_occurrence_impl(args: InsertOccurrenceArgs) -> str:
        """Insert an occurrence for a reported issue. The issue must exist first.

        An occurrence can span multiple locations (e.g., duplicated code across files).
        """
        return insert_occurrence(agent_run_id, args)

    @provider.tool(name="delete_issue")
    def delete_issue_impl(args: DeleteIssueArgs) -> str:
        """Delete a reported issue and all its occurrences. Use to remove incorrect issues."""
        return delete_issue(args)

    @provider.tool(name="list_issues")
    def list_issues_impl() -> str:
        """List all issues reported in this critique run.

        Returns JSON with issue IDs, rationales, and occurrence counts.
        """
        return list_issues(agent_run_id)

    @provider.tool(name="submit")
    def submit_impl(args: SubmitArgs) -> str:
        """Finalize and submit the critique.

        Validates all issues and marks the run as complete. Call this when done reviewing.
        """
        result = submit(agent_run_id, args)
        if result.should_exit:
            exit_state.should_exit = True
            logger.info("Submit tool requested exit")
        return result.output

    @provider.tool(name="report_failure")
    def report_failure_impl(args: ReportFailureArgs) -> str:
        """Report that the critique could not be completed.

        Use when there are blocking issues (e.g., no files in scope).
        """
        result = report_failure(agent_run_id, args)
        if result.should_exit:
            exit_state.should_exit = True
            logger.info("Report failure tool requested exit")
        return result.output

    return provider


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
    exit_state = ExitState()
    tool_provider = create_critic_tool_provider(agent_run_id, exit_state)

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
        AbortIf(lambda: exit_state.should_exit),
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

    await agent.run()
    if exit_state.should_exit:
        print("Critique completed")
        return 0
    # Agent finished without explicit exit (shouldn't happen with proper abort handling)
    logger.warning("Agent finished without explicit exit")
    return 1


def run_critic_loop_sync(system_prompt: str, model: str) -> int:
    """Synchronous wrapper for run_critic_loop."""
    return asyncio.run(run_critic_loop(system_prompt, model))
