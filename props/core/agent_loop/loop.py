"""In-container agent loop for critic agents.

Runs the full agent loop inside the container:
1. Fetches snapshot from Postgres
2. Constructs system prompt
3. Calls LLM via proxy (OPENAI_BASE_URL)
4. Executes tools (both shell exec and critic-specific tools)
5. Exits 0 on successful submit, non-zero on failure
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from openai import OpenAI

from mcp_infra.exec.subprocess_exec import SubprocessExecArgs, get_exec_tool_schema, run_exec
from props.core.critic.tools import (
    DeleteIssueArgs,
    InsertIssueArgs,
    InsertOccurrenceArgs,
    InsertOccurrenceMultiArgs,
    ReportFailureArgs,
    SubmitArgs,
    ToolResult,
    delete_issue,
    get_critic_tool_schemas,
    insert_issue,
    insert_occurrence,
    insert_occurrence_multi,
    list_issues,
    report_failure,
    submit,
)

logger = logging.getLogger(__name__)

# Maximum turns before giving up
MAX_TURNS = 100


def _handle_critic_tool(name: str, arguments: str) -> ToolResult:
    """Handle a critic tool call and return the result."""
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return ToolResult(output=f"Error: Invalid JSON arguments: {e}")

    try:
        if name == "insert_issue":
            return insert_issue(InsertIssueArgs.model_validate(args))
        elif name == "insert_occurrence":
            return insert_occurrence(InsertOccurrenceArgs.model_validate(args))
        elif name == "insert_occurrence_multi":
            return insert_occurrence_multi(InsertOccurrenceMultiArgs.model_validate(args))
        elif name == "delete_issue":
            return delete_issue(DeleteIssueArgs.model_validate(args))
        elif name == "list_issues":
            return list_issues()
        elif name == "submit":
            return submit(SubmitArgs.model_validate(args))
        elif name == "report_failure":
            return report_failure(ReportFailureArgs.model_validate(args))
        else:
            return ToolResult(output=f"Error: Unknown critic tool '{name}'")
    except Exception as e:
        logger.exception("Critic tool error: %s", name)
        return ToolResult(output=f"Error in {name}: {e}")


# Critic tool names for dispatch
CRITIC_TOOLS = {"insert_issue", "insert_occurrence", "insert_occurrence_multi", "delete_issue", "list_issues", "submit", "report_failure"}


async def run_critic_loop(system_prompt: str, model: str) -> int:
    """Run the critic agent loop.

    Args:
        system_prompt: The system prompt for the critic agent
        model: Model name (must match agent_run.model for proxy validation)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    client = OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )

    # Combine exec tool with critic-specific tools
    tools = [get_exec_tool_schema()] + get_critic_tool_schemas()
    messages: list[dict[str, Any]] = []

    for turn in range(MAX_TURNS):
        logger.info("Turn %d", turn + 1)

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

        # Check for text output
        for item in output_items:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        print(content.text)

        # Check for function calls
        function_calls = [item for item in output_items if item.type == "function_call"]

        if not function_calls:
            # No function calls - agent is done but didn't submit
            logger.warning("Agent produced no function calls")
            print("Warning: Agent stopped without calling submit", file=sys.stderr)
            return 1

        # Add assistant message to conversation
        messages.append({"role": "assistant", "content": output_items})

        # Execute function calls
        tool_results = []
        exit_code: int | None = None

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
            elif fc.name in CRITIC_TOOLS:
                # Critic tool - run in Python
                result = _handle_critic_tool(fc.name, fc.arguments)
                output = result.output

                if result.should_exit:
                    exit_code = result.exit_code
                    logger.info("Tool %s requested exit with code %d", fc.name, exit_code)
            else:
                output = f"Error: Unknown tool '{fc.name}'"

            tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": output})

        # Add tool results to conversation
        messages.extend(tool_results)

        # Exit if a tool requested it
        if exit_code is not None:
            if exit_code == 0:
                print("Critique submitted successfully")
            return exit_code

    logger.error("Max turns (%d) exceeded", MAX_TURNS)
    print(f"Error: Max turns ({MAX_TURNS}) exceeded", file=sys.stderr)
    return 1


def run_critic_loop_sync(system_prompt: str, model: str) -> int:
    """Synchronous wrapper for run_critic_loop."""
    return asyncio.run(run_critic_loop(system_prompt, model))
