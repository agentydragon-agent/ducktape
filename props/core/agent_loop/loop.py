"""In-container agent loop for critic agents.

Runs the full agent loop inside the container:
1. Fetches snapshot from Postgres
2. Constructs system prompt
3. Calls LLM via proxy (OPENAI_BASE_URL)
4. Executes tools via subprocess
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

from mcp_infra.exec.direct import DirectExecArgs, run_direct_exec
from mcp_infra.exec.models import Exited

logger = logging.getLogger(__name__)

# Maximum turns before giving up
MAX_TURNS = 100


EXEC_TOOL_DESCRIPTION = (
    "Execute a command in the workspace. Use critic_cli commands "
    "to report issues and submit your critique. Commands run in /workspace directory."
)


def _get_exec_tool_schema() -> dict[str, Any]:
    """Return the exec tool schema for OpenAI Responses API.

    Generates schema from DirectExecArgs Pydantic model.
    """
    parameters = DirectExecArgs.model_json_schema()
    # Remove $defs if present (OpenAI strict mode doesn't support refs)
    parameters.pop("$defs", None)
    return {
        "type": "function",
        "function": {
            "name": "exec",
            "description": EXEC_TOOL_DESCRIPTION,
            "parameters": parameters,
            "strict": True,
        },
    }


def _check_submit_success(command: list[str], exit_code: int) -> bool:
    """Check if this was a successful submit command."""
    # Check if command is a submit command (critic_cli submit ...)
    if len(command) >= 2 and command[0] == "critic_cli" and command[1] == "submit":
        return exit_code == 0
    return False


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

    tools = [_get_exec_tool_schema()]
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
        for fc in function_calls:
            if fc.name != "exec":
                output = f"Error: Unknown tool '{fc.name}'. Only 'exec' is available."
                tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": output})
                continue

            try:
                args = json.loads(fc.arguments)
                exec_args = DirectExecArgs.model_validate(args)
                exec_result = await run_direct_exec(exec_args)
                # Serialize result to JSON for the LLM
                output = exec_result.model_dump_json()

                # Check for successful submit
                if isinstance(exec_result.exit, Exited) and _check_submit_success(exec_args.cmd, exec_result.exit.exit_code):
                    logger.info("Submit succeeded, exiting")
                    print("Critique submitted successfully")
                    return 0

            except json.JSONDecodeError as e:
                output = f"Error: Invalid JSON arguments: {e}"
            except Exception as e:
                output = f"Error executing command: {e}"
                logger.exception("Tool execution error")

            tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": output})

        # Add tool results to conversation
        messages.extend(tool_results)

    logger.error("Max turns (%d) exceeded", MAX_TURNS)
    print(f"Error: Max turns ({MAX_TURNS}) exceeded", file=sys.stderr)
    return 1


def run_critic_loop_sync(system_prompt: str, model: str) -> int:
    """Synchronous wrapper for run_critic_loop."""
    return asyncio.run(run_critic_loop(system_prompt, model))
