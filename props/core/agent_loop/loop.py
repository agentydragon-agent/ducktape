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
from pathlib import Path
from typing import Any

from openai import OpenAI

from mcp_infra.exec.models import MAX_BYTES_CAP, Exited
from mcp_infra.exec.subprocess import run_proc

logger = logging.getLogger(__name__)

# Tool execution timeout (5 minutes)
TOOL_TIMEOUT_SECONDS = 300.0

# Maximum turns before giving up
MAX_TURNS = 100

# Workspace path inside container
WORKSPACE = Path("/workspace")


def _get_exec_tool_schema() -> dict[str, Any]:
    """Return the exec tool schema for OpenAI Responses API."""
    return {
        "type": "function",
        "function": {
            "name": "exec",
            "description": (
                "Execute a command in the workspace. Use this to run props critic-agent commands "
                "to report issues and submit your critique. Commands run in /workspace directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Command array to execute (no shell). "
                            "Example: ['props', 'critic-agent', 'insert-issue', 'dead-code', 'Unused import']"
                        ),
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


async def _execute_tool(command: list[str]) -> str:
    """Execute a command and return the result as a string."""
    logger.info("Executing: %s", " ".join(command))

    outcome = await run_proc(command, timeout_s=TOOL_TIMEOUT_SECONDS, cwd=WORKSPACE)

    # Render output
    stdout = outcome.output.stdout.decode("utf-8", errors="replace")
    stderr = outcome.output.stderr.decode("utf-8", errors="replace")

    # Truncate if needed
    if len(stdout) > MAX_BYTES_CAP:
        stdout = stdout[:MAX_BYTES_CAP] + f"\n... (truncated, {len(outcome.output.stdout)} bytes total)"
    if len(stderr) > MAX_BYTES_CAP:
        stderr = stderr[:MAX_BYTES_CAP] + f"\n... (truncated, {len(outcome.output.stderr)} bytes total)"

    # Build result string
    parts = []
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")

    if isinstance(outcome.exit, Exited):
        parts.append(f"exit_code: {outcome.exit.exit_code}")
    else:
        parts.append(f"exit: {outcome.exit.kind}")

    return "\n".join(parts) if parts else "(no output)"


def _check_submit_success(command: list[str], exit_code: int) -> bool:
    """Check if this was a successful submit command."""
    # Check if command is a submit command
    if len(command) >= 3 and command[0] == "props" and command[1] == "critic-agent" and command[2] == "submit":
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
                result = f"Error: Unknown tool '{fc.name}'. Only 'exec' is available."
                tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": result})
                continue

            try:
                args = json.loads(fc.arguments)
                command = args.get("command", [])
                if not command or not isinstance(command, list):
                    result = "Error: 'command' must be a non-empty array of strings"
                else:
                    result = await _execute_tool(command)

                    # Check for successful submit
                    # Parse exit code from result
                    exit_code = None
                    for line in result.split("\n"):
                        if line.startswith("exit_code: "):
                            try:
                                exit_code = int(line.split(": ", 1)[1])
                            except ValueError:
                                pass

                    if exit_code is not None and _check_submit_success(command, exit_code):
                        logger.info("Submit succeeded, exiting")
                        print("Critique submitted successfully")
                        return 0

            except json.JSONDecodeError as e:
                result = f"Error: Invalid JSON arguments: {e}"
            except Exception as e:
                result = f"Error executing command: {e}"
                logger.exception("Tool execution error")

            tool_results.append({"type": "function_call_output", "call_id": fc.call_id, "output": result})

        # Add tool results to conversation
        messages.extend(tool_results)

    logger.error("Max turns (%d) exceeded", MAX_TURNS)
    print(f"Error: Max turns ({MAX_TURNS}) exceeded", file=sys.stderr)
    return 1


def run_critic_loop_sync(system_prompt: str, model: str) -> int:
    """Synchronous wrapper for run_critic_loop."""
    return asyncio.run(run_critic_loop(system_prompt, model))
