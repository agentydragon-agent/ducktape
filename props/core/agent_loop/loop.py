"""In-container agent loop for critic agents.

Runs the full agent loop inside the container:
1. Fetches agent_run_id from environment
2. Constructs system prompt
3. Calls LLM via proxy (OPENAI_BASE_URL)
4. Executes tools (both shell exec and critic-specific tools)
5. Exits on successful submit or reported failure
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any
from uuid import UUID

from openai import OpenAI
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from mcp_infra.exec.subprocess_exec import SubprocessExecArgs, get_exec_tool_schema, run_exec
from props.core.agent_helpers import get_current_agent_run_id
from props.core.critic.tools import (
    CRITIC_TOOL_NAMES,
    DeleteIssueArgs,
    InsertIssueArgs,
    InsertOccurrenceArgs,
    ReportFailureArgs,
    SubmitArgs,
    ToolResult,
    delete_issue,
    get_critic_tool_schemas,
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


def _handle_critic_tool(agent_run_id: UUID, name: str, arguments: str) -> ToolResult:
    """Handle a critic tool call and return the result."""
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return ToolResult(output=f"Error: Invalid JSON arguments: {e}")

    try:
        if name == "insert_issue":
            return insert_issue(agent_run_id, InsertIssueArgs.model_validate(args))
        elif name == "insert_occurrence":
            return insert_occurrence(agent_run_id, InsertOccurrenceArgs.model_validate(args))
        elif name == "delete_issue":
            return delete_issue(DeleteIssueArgs.model_validate(args))
        elif name == "list_issues":
            return list_issues(agent_run_id)
        elif name == "submit":
            return submit(agent_run_id, SubmitArgs.model_validate(args))
        elif name == "report_failure":
            return report_failure(agent_run_id, ReportFailureArgs.model_validate(args))
        else:
            return ToolResult(output=f"Error: Unknown critic tool '{name}'")
    except Exception as e:
        logger.exception("Critic tool error: %s", name)
        return ToolResult(output=f"Error in {name}: {e}")


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

    client = OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )

    # Combine exec tool with critic-specific tools
    tools = [get_exec_tool_schema()] + get_critic_tool_schemas()
    messages: list[dict[str, Any]] = []

    while True:
        try:
            response = client.responses.create(
                model=model,
                input=messages if messages else system_prompt,
                instructions=system_prompt if messages else None,
                tools=tools,
            )
        except Exception as e:
            logger.error("LLM API error: %s", e)
            print(f"LLM API error: {e}", file=sys.stderr)
            return 1

        # Process response
        output_items = response.output if hasattr(response, "output") else []

        # Check for text output and send reminder if agent tries to output text
        has_text_output = False
        for item in output_items:
            if isinstance(item, ResponseOutputMessage):
                for content in item.content:
                    if isinstance(content, ResponseOutputText) and content.text.strip():
                        has_text_output = True

        # Check for function calls
        function_calls = [item for item in output_items if isinstance(item, ResponseFunctionToolCall)]

        if not function_calls:
            # No function calls - agent is done but didn't submit
            logger.warning("Agent produced no function calls")
            print("Warning: Agent stopped without calling submit", file=sys.stderr)
            return 1

        # Add assistant message to conversation
        messages.append({"role": "assistant", "content": output_items})

        # If agent output text, add a reminder to use tools instead
        if has_text_output:
            messages.append({"role": "user", "content": TEXT_OUTPUT_REMINDER})

        # Execute function calls
        tool_results = []
        should_exit = False

        for fc in function_calls:
            if fc.name == "exec":
                # Shell execution
                try:
                    args = json.loads(fc.arguments)
                    exec_args = SubprocessExecArgs.model_validate(args)
                    exec_result = await run_exec(exec_args)
                    output = exec_result.model_dump_json()
                except json.JSONDecodeError as e:
                    output = f"Error: Invalid JSON arguments: {e}"
                except Exception as e:
                    output = f"Error executing command: {e}"
                    logger.exception("Exec tool error")
            elif fc.name in CRITIC_TOOL_NAMES:
                # Critic tool - run in Python
                result = _handle_critic_tool(agent_run_id, fc.name, fc.arguments)
                output = result.output

                if result.should_exit:
                    should_exit = True
                    logger.info("Tool %s requested exit", fc.name)
            else:
                output = f"Error: Unknown tool '{fc.name}'"

            tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": output})

        # Add tool results to conversation
        messages.extend(tool_results)

        # Exit if a tool requested it
        if should_exit:
            print("Critique completed")
            return 0
