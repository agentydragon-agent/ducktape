"""Parallel prompt optimization system for Claude Code agents.

Iteratively improves CLAUDE.md by running multiple agent rollouts in parallel
on seed programming tasks, grading solutions using OpenAI's Responses API (o3 model),
and using a PromptEngineer to propose improved prompts. All data is logged to JSONL
files for analysis.

Usage:
    python3 prompt_engineer_algorithm.py [--iterations N] [--rollouts-per-task N]

    --iterations N          Number of optimization iterations (default: 10)
    --rollouts-per-task N   Number of agent rollouts per seed task (default: 5)

Key Features:
* Fully parallel rollouts with semaphore-based concurrency control
* Docker containerization for isolated Claude Code agent execution
* OpenAI Responses API integration for grading and prompt engineering
* PromptEngineer class with persistent conversation state and context trimming
* Structured logging with JSON output for comprehensive tracking

Architecture:
* Claude Code agents run in isolated Docker containers for safety
* Rollouts execute in parallel (configurable max concurrency)
* OpenAI o3 model handles both grading and prompt engineering
* Context trimming preserves reasoning token validity
* JSONL logs capture all API interactions and results

Configuration:
* Parallelism: Adjust MAX_PARALLEL_ROLLOUTS constant (default: 8)
* Context limits: PromptEngineer handles 200k token o3 context automatically
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import shutil
import structlog
import sys
import tiktoken
import yaml
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from claude_code_sdk import (
    query as claude_query,
    ClaudeCodeOptions,
    ClaudeSDKClient,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from openai import OpenAI
from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from pydantic import BaseModel

# Configure structured logging
import logging

logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Configuration constants
OPENAI_MODEL = "o3"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 4000
BASH_TIMEOUT_MS = "30000"
TRUNCATION_LENGTH = 80


class ProcessingMode(Enum):
    """Processing mode for prompt optimization."""
    FULL_ROLLOUTS = "full_rollouts"
    SUMMARY = "summary"
MAX_PARALLEL_ROLLOUTS = 8  # Maximum concurrent Claude Code rollouts


class SeedTask(BaseModel):
    id: str
    prompt: str


class Criterion(BaseModel):
    name: str
    description: str
    evaluation_criteria: str


# Capture original PATH and binary locations before any modifications.
# We use Docker to run Claude Code agents in isolated containers for safety.
# This ensures that when we inject wrapper scripts into PATH, we can still
# locate the real Docker binary. The absolute path is captured once at
# module load time so that subsequent PATH modifications don't shadow it.
_ORIGINAL_PATH = os.environ.get("PATH", "")
_ORIGINAL_DOCKER_PATH = shutil.which("docker", path=_ORIGINAL_PATH)
if _ORIGINAL_DOCKER_PATH is None:
    raise RuntimeError(
        "Docker is required to run Claude Code agents in isolated containers. "
        "Install Docker and ensure it is in your PATH."
    )

# -----------------------------------------------------------------------------
# Helper functions for deduplication and common operations
# -----------------------------------------------------------------------------


def truncate_string(text: str, max_len: int = TRUNCATION_LENGTH) -> str:
    """Truncate string to max_len chars with ellipsis if needed."""
    return text[:max_len] + "..." if len(text) > max_len else text


def safe_model_dump(obj: Any) -> Dict[str, Any]:
    """Convert object to dict using proper type checking."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    elif isinstance(obj, dict):
        return obj
    else:
        return {"value": obj}


def create_openai_request(
    model: str,
    input_data: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_choice: Dict[str, Any],
    reasoning_effort: str = REASONING_EFFORT,
    max_tokens: int = MAX_OUTPUT_TOKENS,
) -> Dict[str, Any]:
    """Create standardized OpenAI request dictionary."""
    request = {
        "model": model,
        "input": input_data,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    if reasoning_effort:
        request["reasoning"] = {"effort": reasoning_effort}
    if max_tokens:
        request["max_output_tokens"] = max_tokens
    return request


# ----------------------------------------------------------------------------
# Helper functions for message summarisation
#
# The logging logic inside run_claude_code originally contained a large block
# of repetitive code to detect tool invocations, extract argument strings and
# derive text prefixes.  To improve clarity and maintainability, this
# functionality is refactored into a few small helper functions.  These
# helpers encapsulate the common patterns of formatting arguments, summarising
# tool calls, summarising tool results, and extracting text prefixes.  By
# delegating to these helpers, the main loop in run_claude_code becomes
# easier to read and future changes to the summarisation logic can be
# made in one place.


def format_args(args: Any, max_length: int = TRUNCATION_LENGTH) -> str:
    """Format tool arguments for display in logs.

    If ``args`` is a dictionary, render it as ``key: value`` pairs separated
    by commas, truncating long values.  For other types, serialise to JSON
    or string and truncate to ``max_length`` characters.

    Parameters
    ----------
    args : Any
        The arguments to format.  Usually a dict or a serialisable type.
    max_length : int
        Maximum length of the formatted argument string.

    Returns
    -------
    str
        A human‑readable representation of the arguments.
    """
    try:
        if isinstance(args, dict):
            parts: List[str] = []
            for k, v in args.items():
                v_str = str(v)
                if len(v_str) > max_length:
                    v_str = v_str[:max_length] + "..."
                parts.append(f"{k}: {v_str}")
            return ", ".join(parts)
        else:
            # Fallback: JSON serialise or just use str()
            try:
                arg_str = json.dumps(args)
            except Exception:
                arg_str = str(args)
            if len(arg_str) > max_length:
                arg_str = arg_str[:max_length] + "..."
            return arg_str
    except (AttributeError, TypeError):
        # If formatting fails, return a simple representation
        return str(args)[:max_length] + ("..." if len(str(args)) > max_length else "")


def log_message_summary(message: Any, agent_id: int) -> None:
    """Log a structured summary of a Claude Code SDK message."""

    def truncate(text: str, limit: int = 100) -> str:
        return text[:limit] + "..." if len(text) > limit else text

    def clean_text(text: str) -> str:
        return text.replace("\n", " ")

    def safe_content_to_str(content: Any) -> str:
        """Safely convert content to string, handling both str and list types."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Handle list content by converting to string representation
            return str(content)
        else:
            return str(content)

    message_logger = logger.bind(agent_id=agent_id, message_type=type(message).__name__)

    if isinstance(message, SystemMessage):
        message_logger.info("System message", subtype=message.subtype)

    elif isinstance(message, AssistantMessage):
        tool_uses = []
        text_content = ""

        for block in message.content:
            if isinstance(block, TextBlock):
                text_content = block.text
            elif isinstance(block, ToolUseBlock):
                args = ", ".join(
                    f"{k}={truncate(str(v), 30)}" for k, v in block.input.items()
                )
                tool_uses.append(f"{block.name}({args})")
            elif isinstance(block, ToolResultBlock):
                content = (
                    block.content
                    if isinstance(block.content, str)
                    else str(block.content)
                )
                message_logger.info(
                    "Tool result",
                    tool_use_id=block.tool_use_id[:8],
                    content_preview=clean_text(truncate(content, 60)),
                )

        if tool_uses:
            message_logger.info("Tool usage", tools=tool_uses)
        elif text_content:
            message_logger.info(
                "Assistant message", content_preview=clean_text(truncate(text_content))
            )

    elif isinstance(message, UserMessage):
        # UserMessage.content can be a string or list - handle both safely
        content_str = safe_content_to_str(message.content)

        if isinstance(message.content, list) and message.content:
            # Handle list content (e.g., tool results)
            first_item = message.content[0]
            if isinstance(first_item, dict) and first_item.get("type") == "tool_result":
                tool_id = first_item.get("tool_use_id", "unknown")[:8]
                content = first_item.get("content", "")
                content_str = content if isinstance(content, str) else str(content)
                message_logger.info(
                    "Tool result",
                    tool_use_id=tool_id,
                    content_preview=clean_text(truncate(content_str, 60)),
                )
            else:
                message_logger.info(
                    "User message", content_preview=clean_text(truncate(content_str))
                )
        elif content_str:
            message_logger.info(
                "User message", content_preview=clean_text(truncate(content_str))
            )
        else:
            message_logger.info("User message", content="empty")

    elif isinstance(message, ResultMessage):
        message_logger.info(
            "Result message",
            duration_ms=message.duration_ms,
            cost_usd=message.total_cost_usd,
            is_error=message.is_error,
        )

    else:
        message_logger.info("Unknown message type")


def extract_text_prefix(text: str, limit: int = 120) -> str:
    """Extract the first ``limit`` characters from a block of text.

    Newlines are replaced with spaces to provide a single‑line preview.

    Parameters
    ----------
    text : str
        The text to extract from.
    limit : int
        Maximum number of characters to return.
    """
    try:
        if not isinstance(text, str):
            text = str(text)
        single_line = text.replace("\n", " ").strip()
        return single_line[:limit]
    except (AttributeError, TypeError):
        return str(text)[:limit] if text else ""


def summarise_tool(block: Any) -> Optional[str]:
    """Return a succinct summary of a tool invocation from a Claude Code block.

    The Claude Code SDK represents tool calls with objects that may expose
    attributes such as ``tool`` (an object with a ``name``), ``name`` (the
    tool name as a string), and arguments via ``input``, ``arguments`` or
    ``args``.  This function inspects these attributes to derive a summary
    like ``Write(path: foo.py)``.  If no tool invocation is detected, it
    returns ``None``.

    Parameters
    ----------
    block : Any
        A content block from Claude Code.  Could be a TextBlock or ToolUseBlock.

    Returns
    -------
    Optional[str]
        A formatted tool summary, or None if not a tool invocation.
    """
    try:
        # Case 1: block has a 'tool' attribute with its own name and args
        if hasattr(block, "tool"):
            tool_obj = getattr(block, "tool")
            try:
                tool_name = (
                    getattr(tool_obj, "name")
                    if hasattr(tool_obj, "name")
                    else str(tool_obj)
                )
            except (AttributeError, TypeError):
                tool_name = str(tool_obj)
            args = None
            # The block may expose arguments on itself
            if hasattr(block, "arguments"):
                args = getattr(block, "arguments")
            elif hasattr(block, "args"):
                args = getattr(block, "args")
            if args is not None:
                return f"{tool_name}({format_args(args)})"
            else:
                return tool_name
        # Case 2: block directly exposes a 'name' and arguments (ToolUseBlock)
        if hasattr(block, "name"):
            tool_name = None
            try:
                tool_name = getattr(block, "name")
            except AttributeError:
                tool_name = None
            if tool_name:
                # Collect arguments from possible attributes
                args = None
                if hasattr(block, "input"):
                    args = getattr(block, "input")
                elif hasattr(block, "arguments"):
                    args = getattr(block, "arguments")
                elif hasattr(block, "args"):
                    args = getattr(block, "args")
                if args is not None:
                    return f"{tool_name}({format_args(args)})"
                else:
                    return tool_name
        return None
    except (AttributeError, KeyError, TypeError):
        return None


def summarise_tool_result(content: Any) -> Optional[str]:
    """Summarise a tool result from the message content.

    Tool results are returned as dictionaries with keys ``type`` and
    ``content`` or as string representations of such dictionaries.  If the
    content represents a tool result, this function returns a summary like
    ``tool_result(File created successfully...)``.  Otherwise returns None.

    Parameters
    ----------
    content : Any
        The content field of a Claude Code message.

    Returns
    -------
    Optional[str]
        A formatted summary of the tool result, or None if the content is
        not recognised as a tool result.
    """
    try:
        # Direct dict representation
        if isinstance(content, dict):
            if content.get("type") == "tool_result":
                result_text = content.get("content", "")
                if isinstance(result_text, list):
                    result_text = str(result_text)
                result_text_str = extract_text_prefix(str(result_text), limit=120)
                return f"tool_result({result_text_str})"
        # String representation of a dict
        if isinstance(content, str):
            import ast

            try:
                parsed = ast.literal_eval(content)
                if isinstance(parsed, dict) and parsed.get("type") == "tool_result":
                    result_text = parsed.get("content", "")
                    if isinstance(result_text, list):
                        result_text = str(result_text)
                    result_text_str = extract_text_prefix(str(result_text), limit=120)
                    return f"tool_result({result_text_str})"
            except (AttributeError, TypeError):
                pass
        return None
    except (AttributeError, TypeError):
        return None


# -----------------------------------------------------------------------------
# Prompt templates
#
# To make it easier to adjust the language used in prompts or to reuse them in
# different contexts, we define them as module-level constants.  Templates use
# brace-style placeholders (e.g. {task}, {combined_code}) which are filled at
# runtime using str.format().

# The system message for the prompt engineer agent.  This message remains
# constant across iterations and reminds the model of its role.  It also
# instructs the model to call the submit_prompt function when given
# rollouts and grades.
PROMPT_ENGINEER_SYSTEM_MESSAGE = (
    "You are a prompt engineer tasked with refining system prompts for a Python coding assistant. "
    "When you are given rollouts and grades from the last prompt, call the `submit_prompt` function with "
    "a single argument `prompt` containing your improved system prompt. Do not output anything else. "
    "The coding assistant works through tools providing it I/O access to a filesystem and to shell "
    "command execution."
)

# -----------------------------------------------------------------------------
# Helper functions for logging API requests and responses
#
# These functions write JSONL entries for every call to the OpenAI and Anthropic
# APIs.  Each entry includes a timestamp, the request parameters, and the
# response or event data.  They are used throughout the script to aid in
# debugging and auditing of API interactions.


def log_openai_request_response(
    log_path: Path, request: Dict[str, Any], response: Any
) -> None:
    """Append a record of an OpenAI API request and its response to a JSONL file.

    Parameters
    ----------
    log_path : Path
        The path to the JSONL log file.
    request : dict
        A dictionary representing the parameters sent to the OpenAI API.
    response : Any
        The response object returned by the OpenAI library.  We attempt to
        serialise it to JSON; if that fails, we fall back to its string
        representation.
    """
    # Attempt to serialise the response object.  OpenAI responses implement a
    # model_dump() method; if unavailable, fall back to dict(), json(), or str().
    try:
        response_data = (
            response.model_dump()
            if isinstance(response, BaseModel)
            else {"value": str(response)}
        )
    except (AttributeError, TypeError):
        response_data = {"value": str(response)}
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "request": request,
        "response": response_data,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def log_anthropic_request_event(
    log_path: Path, request: Dict[str, Any], event: Any
) -> None:
    """Append a record of an Anthropic request or response event to a JSONL file.

    The caller should first log the request once, then log each event yielded
    by the Claude Code asynchronous generator.  Events are serialised if
    possible; otherwise they are converted to strings.

    Parameters
    ----------
    log_path : Path
        The path to the JSONL log file.
    request : dict
        The request parameters sent to Claude Code, typically containing
        messages and options.
    event : Any
        An event returned by the Claude Code async generator.  Could be a
        dictionary or a string.
    """
    try:
        event_data = event if isinstance(event, dict) else str(event)
    except (AttributeError, TypeError):
        event_data = str(event)
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "request": request,
        "event": event_data,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


class CodeResult(BaseModel):
    """Represents the outcome of running Claude Code on a programming task.

    A CodeResult contains only the essential metadata for an agent rollout: the
    task description, the agent identifier, the generated source code, and a
    timestamp.  It deliberately omits any rationale, since explanations belong
    to the grading step rather than the code generation step.
    """

    task: str
    agent_id: int
    code: str
    timestamp: str
    messages: List[Dict[str, Any]]
    files: List[Dict[str, str]]


# Criterion class already defined above with Pydantic


class Grade(BaseModel):
    """Represents the grading information for a piece of code.

    A Grade stores a mapping from criterion keys to scores and rationales, as
    well as an overall score and rationale.  This structure allows for a
    variable number of grading axes defined by the user via the Criterion
    list.  The overall score is provided by the grader and should reflect
    holistic quality, not a simple average of axis scores.
    """

    task: str
    agent_id: int
    axis_scores: Dict[str, float]
    axis_rationales: Dict[str, str]
    overall_score: float
    overall_rationale: str
    timestamp: str


async def run_claude_code(
    task: str,
    system_prompt: str,
    agent_id: int,
    task_id: str,
    base_dir: Path,
    anthropic_log_path: Path,
    prompt_version: int,
) -> CodeResult:
    """Run a single Claude Code agent on the given task.

    This function sets up an isolated working directory for the agent,
    writes the system prompt to a uniquely numbered ``CLAUDE-XXXX.md``
    file (where XXXX is the prompt version), and then queries the
    Claude Code model to generate code that solves the task.  The returned
    CodeResult contains the generated code and any rationale provided
    by the model.

    Parameters
    ----------
    task : str
        The user-facing task description for which code should be generated.
    system_prompt : str
        The system prompt guiding the agent's behaviour.
    agent_id : int
        An identifier distinguishing this agent instance within a batch.
    base_dir : Path
        The path where the agent's working directory should be created.

    Returns
    -------
    CodeResult
        A dataclass containing the task, agent identifier, generated code,
        rationale, and timestamp.
    """
    # Create a unique working directory for this agent
    # Use an absolute path for the working directory to ensure the SDK runs in
    # the intended location regardless of the current working directory.  The
    # resolved path also prevents relative path traversal issues.
    # Include task_id and agent_id to avoid conflicts when multiple agents work on different tasks
    work_dir = (base_dir / f"task_{task_id}" / f"agent_{agent_id}").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    # Log the working directory for this agent so that users
    # know where the agent's files are being saved.  This occurs at the start
    # of each agent run.
    agent_logger = logger.bind(agent_id=agent_id, task_id=task_id)
    agent_logger.info("Agent starting", work_dir=str(work_dir), task_preview=task[:100])

    # Write the system prompt into CLAUDE.md inside the agent's working directory.
    # The actual prompt version files are stored at the run directory level.
    prompt_file = work_dir / "CLAUDE.md"
    prompt_file.write_text(system_prompt)

    # No additional scaffolding is added; the task itself serves as the prompt for Claude Code.

    # Set bash timeout environment variable (30 seconds)
    os.environ["BASH_MAX_TIMEOUT_MS"] = BASH_TIMEOUT_MS

    # Configure Claude Code options.  We always expect the SDK and API key to be present.
    options = ClaudeCodeOptions(
        # Enable ALL tools including dangerous ones like Bash for full execution
        allowed_tools=None,  # None means all tools are allowed
        # Use a Path object for cwd to ensure the SDK respects the working directory
        cwd=work_dir,
        # Allow up to 100 conversational turns so the agent has enough
        # interactions to solve complex tasks.
        max_turns=100,
        # Auto‑accept ALL permissions - dangerous but needed for full execution
        permission_mode="bypassPermissions",  # Bypass all permissions automatically
        # Disable all MCP servers to prevent interference and resource usage
        mcp_servers={},  # Empty dict means no MCP servers
    )
    # Collect the full sequence of messages/events from the Claude Code agent.  Each
    # event returned by the SDK is appended verbatim to a list so that the
    # prompt engineer can see the entire interaction history.  We make no
    # attempt to summarise or drop information at this stage; token budget
    # management happens later in the prompt engineer conversation.
    message_sequence: List[Dict[str, Any]] = []
    # Prepare request object for logging
    anthropic_request = {
        "prompt": task,
        "options": (
            options.model_dump() if isinstance(options, BaseModel) else str(options)
        ),
    }
    # Log the request before sending
    log_anthropic_request_event(anthropic_log_path, anthropic_request, "request_sent")

    # Debug: Log session start
    agent_logger.info("Starting Claude Code session")
    # Import the correct message types from the SDK and use ClaudeSDKClient for streaming mode
    from claude_code_sdk import (
        ResultMessage,
    )

    # Use ClaudeSDKClient to force streaming mode
    async with ClaudeSDKClient(options=options) as client:
        await client.query(task)
        async for message in client.receive_messages():
            # Log each event from the Claude Code API
            log_anthropic_request_event(anthropic_log_path, anthropic_request, message)

            # Store the message using dataclasses.asdict() for proper serialization
            message_sequence.append(asdict(message))

            log_message_summary(message, agent_id)

            # Break out of the loop when we receive a ResultMessage (conversation is complete)
            if isinstance(message, ResultMessage):
                agent_logger.info(
                    "Session completed",
                    duration_ms=message.duration_ms,
                    cost_usd=message.total_cost_usd,
                    is_error=message.is_error,
                )
                break

    # After the conversation completes, gather all files in the agent directory
    files_info: List[Dict[str, str]] = []
    for file_path in work_dir.rglob("*"):
        if file_path.is_file() and file_path.name != "CLAUDE.md":
            relative = file_path.relative_to(work_dir).as_posix()
            try:
                content = file_path.read_text()
            except (OSError, UnicodeDecodeError):
                content = ""
            files_info.append({"path": relative, "content": content})

    # Concatenate code from all files for convenience
    code_sections = []
    for f in files_info:
        code_sections.append(f"### {f['path']}\n{f['content']}")
    combined_code = "\n\n".join(code_sections).strip()
    timestamp = datetime.utcnow().isoformat()
    return CodeResult(
        task=task,
        agent_id=agent_id,
        code=combined_code,
        timestamp=timestamp,
        messages=message_sequence,
        files=files_info,
    )


async def grade_code(
    result: CodeResult, criteria: List[Criterion], openai_log_path: Path
) -> Grade:
    """Grade a piece of code using the OpenAI Responses API with function calling.

    The grader evaluates the code on a set of facets (criteria) defined by the
    caller.  Each facet must have a unique key, a description, and an
    evaluation criteria explaining how to assess it.  The grader uses a
    function call (`submit_grades`) to return scores and rationales for each
    facet plus an overall score and rationale.  The overall score is left to
    the model's discretion; it is not computed as the average of the facet
    scores.

    Parameters
    ----------
    result : CodeResult
        The code result to be graded.
    criteria : List[Criterion]
        Facets to evaluate.  Each facet will appear as a
        property in the function schema.
    openai_log_path : Path
        Path to JSONL file where requests and responses to the OpenAI API
        will be logged.
    """
    client = OpenAI()

    # Dynamically build the function schema for the grader based on the
    # provided criteria.  Each facet becomes a property in the function
    # parameters with its own score and rationale fields.  We also include
    # an 'overall' property for the overall assessment.
    properties: Dict[str, Any] = {}
    required_keys: List[str] = []
    for crit in criteria:
        properties[crit.name] = {
            "type": "object",
            "description": f"{crit.description} {crit.evaluation_criteria}",
            "properties": {
                "score": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["score", "rationale"],
            "additionalProperties": False,
        }
        required_keys.append(crit.name)
    # Add overall property
    properties["overall"] = {
        "type": "object",
        "description": "Overall assessment of the solution, including a score from 0 to 10 and a brief rationale.",
        "properties": {
            "score": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": ["score", "rationale"],
        "additionalProperties": False,
    }
    required_keys.append("overall")

    grading_tool = {
        "type": "function",
        "name": "submit_grades",
        "description": (
            "Return scores and rationales for each grading facet. Evaluate the code on the specified facets and "
            "provide an overall score and rationale."
        ),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required_keys,
            "additionalProperties": False,
        },
        "strict": True,
    }

    # Build the input messages.  We give the model the task description and
    # concatenated code, and instruct it to evaluate according to the facets.
    input_messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert Python instructor and code reviewer. For the given task and code, "
                "evaluate the submission according to the provided facets and then call the submit_grades "
                "function with your scores and rationales."
            ),
        },
        {
            "role": "user",
            "content": f"Task: {result.task}\n\nCode:\n{result.code}",
        },
    ]

    # Prepare request for logging
    openai_request = {
        "model": "o3",
        "input": input_messages,
        "tools": [grading_tool],
        "tool_choice": {"type": "function", "name": "submit_grades"},
    }

    # Call the model.  We enforce the tool choice so the model must call
    # submit_grades and return the grading JSON according to the schema.
    grade_logger = logger.bind(
        agent_id=result.agent_id, task_id=getattr(result, "task_id", "unknown")
    )
    grade_logger.info("Making OpenAI grading call")

    openai_request = create_openai_request(
        OPENAI_MODEL,
        input_messages,
        [grading_tool],
        {"type": "function", "name": "submit_grades"},
        REASONING_EFFORT,
    )
    response = client.responses.create(**openai_request)
    # Log request and response
    log_openai_request_response(openai_log_path, openai_request, response)
    grade_logger.info("OpenAI grading completed")

    # Extract the function_call item from the response first
    call = None
    for item in response.output or []:
        item_type = getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )
        if item_type == "function_call":
            call = item
            break

    if call is None:
        raise RuntimeError("No function_call found in grading response")

    # Extract and log grading results before processing
    args_str = call.arguments if hasattr(call, "arguments") else call.get("arguments")
    if isinstance(args_str, str):
        grades_data = json.loads(args_str)
        facet_results = {}
        for facet_name, facet_data in grades_data.items():
            if isinstance(facet_data, dict) and "score" in facet_data:
                score = facet_data.get("score", 0)
                rationale = facet_data.get("rationale", "")
                facet_results[facet_name] = {"score": score, "rationale": rationale}

        grade_logger.info("Grading results", facets=facet_results)

        # Also log readable results for each facet
        for facet_name, facet_data in facet_results.items():
            score = facet_data["score"]
            rationale = truncate_string(facet_data["rationale"], TRUNCATION_LENGTH)
            grade_logger.info(
                "Facet graded",
                facet=facet_name,
                score=score,
                rationale=truncate_string(rationale, TRUNCATION_LENGTH),
            )

    if call is None:
        raise RuntimeError("The grader did not call submit_grades as required.")
    # Determine the function name
    call_name = call.name if hasattr(call, "name") else call.get("name")
    if call_name != "submit_grades":
        raise RuntimeError(f"Unexpected function name: {call_name}")
    # Extract the arguments string
    try:
        args_str = (
            call.arguments if hasattr(call, "arguments") else call.get("arguments")
        )
    except (AttributeError, KeyError, TypeError):
        args_str = None
    if not isinstance(args_str, str):
        raise ValueError(
            f"Could not retrieve arguments from submit_grades call: {call}"
        )
    # Parse the JSON string into a dict
    result_data = json.loads(args_str)

    # Map scores and rationales back into the Grade object
    axis_scores: Dict[str, float] = {}
    axis_rationales: Dict[str, str] = {}
    for crit in criteria:
        section = result_data.get(crit.name)
        if not section:
            raise ValueError(
                f"Grading output missing facet '{crit.name}': {result_data}"
            )
        axis_scores[crit.name] = float(section.get("score", 0))
        axis_rationales[crit.name] = str(section.get("rationale", ""))
    overall_section = result_data.get("overall")
    if not overall_section:
        raise ValueError(f"Grading output missing 'overall' section: {result_data}")
    overall_score = float(overall_section.get("score", 0))
    overall_rationale = str(overall_section.get("rationale", ""))
    timestamp = datetime.utcnow().isoformat()
    return Grade(
        task=result.task,
        agent_id=result.agent_id,
        axis_scores=axis_scores,
        axis_rationales=axis_rationales,
        overall_score=overall_score,
        overall_rationale=overall_rationale,
        timestamp=timestamp,
    )


@dataclass
class Turn:
    """A complete conversational turn in the PromptEngineer."""

    reasoning: List[Any]  # OpenAI reasoning from propose()
    function_call_message: ResponseFunctionToolCall  # The original function call message from OpenAI
    proposed_prompt: str  # The prompt that was proposed (extracted from function call)
    grades: str  # Grading results from testing the prompt

    @property
    def messages(self) -> List[Dict[str, Any]]:
        """Convert turn into OpenAI API message sequence with function calling format."""
        msgs = []

        # Add all reasoning items (filtered to remove response-only fields)
        for reasoning_item in self.reasoning:
            msg_dict = reasoning_item.model_dump()
            if 'status' in msg_dict:
                del msg_dict['status']
            msgs.append(msg_dict)

        # Add the original function call message (preserving OpenAI's original object/IDs)
        function_call_dict = self.function_call_message.model_dump()
        if 'status' in function_call_dict:
            del function_call_dict['status']
        msgs.append(function_call_dict)

        # Add function call output with grading results
        function_output_msg = {
            "type": "function_call_output",
            "call_id": self.function_call_message.call_id,
            "output": json.dumps({"grading_results": self.grades})
        }
        msgs.append(function_output_msg)

        return msgs


class PromptEngineer:
    """Manages conversation state and token counting for prompt optimization."""

    # System message preserved across all context trims
    # Note: PE does not get the full text of the grading criteria - only the
    # scores and rationales from the grader. This keeps the context compact
    # and lets the PE focus on patterns in the results rather than memorizing criteria.
    _SYSTEM_MESSAGE = {
        "role": "system",
        "content": "You are a prompt engineer. Your job is to analyze rollouts from coding tasks and iteratively improve the system prompt to get better results.",
    }

    def __init__(self) -> None:
        """Initialize empty conversation state."""
        self._turns: List[Turn] = []

    @property
    def prompt_messages(self) -> List[Any]:
        """Get conversation messages with system message prepended."""
        messages = [self._SYSTEM_MESSAGE]

        # Flatten all turns using their message getter
        for turn in self._turns:
            messages.extend(turn.messages)

        return messages

    def _count_tokens(self, model: str = "gpt-4o") -> int:
        """Private: Count tokens in current conversation."""
        enc = tiktoken.encoding_for_model(model)
        tokens = 0

        # Use the same logic as before - just count all messages in prompt_messages
        for m in self.prompt_messages:
            if hasattr(m, "model_dump"):
                # OpenAI SDK object - serialize it
                m_str = str(m.model_dump())
                tokens += len(enc.encode(m_str))
            elif isinstance(m, dict):
                # Dict message - serialize relevant fields
                if "content" in m:
                    tokens += len(enc.encode(str(m["content"])))
                if "arguments" in m:
                    tokens += len(enc.encode(str(m["arguments"])))
                if "output" in m:
                    tokens += len(enc.encode(str(m["output"])))
            else:
                # Fallback - serialize the whole thing
                tokens += len(enc.encode(str(m)))

        return tokens

    def _trim_context_if_needed(self, max_tokens: int = 140000) -> None:
        """Private: Trim conversation if it exceeds token limit."""
        if self._count_tokens() > max_tokens and len(self._turns) > 2:
            # Keep only last 2 complete turns - each turn is atomic and complete
            self._turns = self._turns[-2:]
            logger.info(
                "Trimmed context",
                remaining_turns=len(self._turns),
                estimated_tokens=self._count_tokens(),
            )

    def _build_rollout_summaries(
        self, rollouts: List[Tuple[CodeResult, Grade]]
    ) -> List[str]:
        """Build summaries of rollout results for conversation."""
        summaries = []
        for code_result, grade in rollouts:
            # Keep messages as SDK objects, serialize them simply as JSON for the LLM
            message_lines = [json.dumps(evt) for evt in code_result.messages]
            code_lines = [f"### {f['path']}\n{f['content']}" for f in code_result.files]
            score_parts = [f"  {k}={v}" for k, v in grade.axis_scores.items()]
            rationale_parts = [f"  {k}: {v}" for k, v in grade.axis_rationales.items()]

            summary = f"""Task: {code_result.task}
Overall Grade: {grade.overall_score}
Axis Scores:
{chr(10).join(score_parts)}
Axis Rationales:
{chr(10).join(rationale_parts)}
Full Code:
{chr(10).join(code_lines)}
Full Messages:
{chr(10).join(message_lines)}"""
            summaries.append(summary)
        return summaries

    def build_grades_message(self, rollouts: List[Tuple[CodeResult, Grade]]) -> str:
        """Build grades message from rollout results."""
        rollout_summaries = self._build_rollout_summaries(rollouts)
        return f"Here are the results from testing the current system prompt on {len(rollouts)} coding tasks. Please analyze these results and propose an improved system prompt.\n\n{chr(10).join(['---'] * 2).join(rollout_summaries)}"

    async def propose_prompt(self, openai_log_path: Path) -> Tuple[List[Any], ResponseFunctionToolCall, str]:
        """Make OpenAI API call to get next prompt proposal.

        Returns:
            (reasoning_messages, function_call_message, proposed_prompt)
        """
        # Trim context if needed before API call
        self._trim_context_if_needed()

        # Create OpenAI Responses API tools schema
        tools = [
            {
                "type": "function",
                "name": "submit_prompt",
                "description": "Submit an improved system prompt",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The improved system prompt",
                        }
                    },
                    "required": ["prompt"],
                },
            }
        ]

        # Call OpenAI Responses API with current conversation
        client = OpenAI()
        openai_request = create_openai_request(
            OPENAI_MODEL,
            self.prompt_messages,
            tools,
            {"type": "function", "name": "submit_prompt"},
        )
        response: Response = client.responses.create(**openai_request)
        log_openai_request_response(openai_log_path, openai_request, response)

        # Separate reasoning messages from function call
        reasoning_messages = []
        function_call_item: Optional[Any] = None

        for item in response.output:
            if getattr(item, "type", None) == "function_call":
                function_call_item = item
            else:
                reasoning_messages.append(item)

        if function_call_item is None:
            raise RuntimeError("No function_call found in response")

        # Extract function call details with proper type checking
        if isinstance(function_call_item, ResponseFunctionToolCall):
            call_name = function_call_item.name
            arguments_str = function_call_item.arguments
        elif isinstance(function_call_item, dict):
            call_name = function_call_item.get("name")
            arguments_str = function_call_item.get("arguments")
        else:
            call_name = getattr(function_call_item, "name", None)
            arguments_str = getattr(function_call_item, "arguments", None)

        if call_name != "submit_prompt":
            raise RuntimeError(f"Unexpected function name: {call_name}")

        if not isinstance(arguments_str, str):
            raise ValueError(f"Invalid arguments format: {arguments_str}")

        try:
            args_dict = json.loads(arguments_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Could not parse arguments: {arguments_str}") from e

        claude_prompt = args_dict.get("prompt", "").strip()
        if not claude_prompt:
            raise ValueError("Empty prompt returned")

        logger.info(
            "Generated new prompt",
            prompt_length=len(claude_prompt),
            conversation_turns=len(self._turns),
        )

        return reasoning_messages, function_call_item, claude_prompt

    def add_result(
        self, reasoning: List[Any], function_call_message: ResponseFunctionToolCall, proposed_prompt: str, grades: str
    ) -> None:
        """Add completed turn to conversation history.

        Args:
            reasoning: OpenAI's reasoning messages from propose_prompt()
            function_call_message: The original function call message from OpenAI
            proposed_prompt: The prompt that was proposed and tested
            grades: Grading results from testing this prompt
        """
        turn = Turn(reasoning=reasoning, function_call_message=function_call_message, proposed_prompt=proposed_prompt, grades=grades)
        self._turns.append(turn)

        logger.info(
            "Added turn to conversation",
            conversation_turns=len(self._turns),
            grades_length=len(grades),
        )


def load_criteria_from_yaml(graders_yaml_path: Path) -> List[Criterion]:
    """Load grading criteria from YAML file."""
    with graders_yaml_path.open("r") as f:
        data = yaml.safe_load(f)

    criteria = []
    for entry in data["graders"]:
        try:
            criterion = Criterion(
                id=entry["id"],
                name=entry["name"],
                description=entry["description"],
                evaluation_criteria=entry["evaluation_criteria"],
            )
            criteria.append(criterion)
        except KeyError as e:
            raise ValueError(f"Invalid grader entry {entry}: missing key {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid grader entry {entry}: {e}") from e

    return criteria


async def optimize_prompts(
    seed_tasks: List[str],
    iterations: int = 3,
    rollouts_per_task: int = 2,
    processing_mode: ProcessingMode = ProcessingMode.FULL_ROLLOUTS,
    base_output_dir: str = "./agent_output",
    max_parallel_rollouts: int = MAX_PARALLEL_ROLLOUTS,
) -> None:
    """Run the prompt optimisation loop.

    This is the main entry point for running multiple iterations of the algorithm. It
    repeatedly executes batches of Claude Code agents on the seed tasks in parallel,
    grades the generated solutions using OpenAI's Responses API, updates the system
    prompt using a prompt engineer (OpenAI o3), and logs results to JSONL files.

    Parameters
    ----------
    seed_tasks : List[SeedTask]
        The programming tasks to use as the benchmark for optimisation.
    iterations : int, optional
        The number of optimisation iterations to perform (default 3).
    rollouts_per_task : int, optional
        The number of Claude Code agents to sample per task in each iteration (default 2).
    base_output_dir : str, optional
        Base directory where agent working directories and logs will be stored.
    max_parallel_rollouts : int, optional
        Maximum number of concurrent Claude Code rollouts (default 8).
    """
    # Create a unique prefix for this run to avoid collisions with previous
    # executions.  The prefix is based on the current UTC timestamp.  All
    # working directories and logs for this run will be stored under
    # base_output_dir / run_prefix.
    run_prefix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = (Path(base_output_dir) / run_prefix).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Run directory created", run_directory=str(base_dir), run_prefix=run_prefix
    )

    # ---------------------------------------------------------------------
    # Docker wrapper setup
    #
    # Use external docker wrapper script as a transparent Claude Code proxy
    # This enables running Claude Code agents in isolated Docker containers
    wrapper_dir = base_dir / "bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_script = wrapper_dir / "claude"

    # Copy the external Docker wrapper script that runs Claude Code in containers
    external_wrapper = Path(__file__).parent / "docker_claude_wrapper.sh"
    shutil.copy2(external_wrapper, wrapper_script)
    wrapper_script.chmod(0o755)

    # Prepend wrapper directory to PATH so Claude Code SDK uses our Docker wrapper
    os.environ["PATH"] = f"{wrapper_dir}:{_ORIGINAL_PATH}"
    logger.info("Docker wrapper configured", wrapper_script=str(wrapper_script))

    # Prepare JSONL log files
    inner_log_path = base_dir / "inner_agent_log.jsonl"
    grader_log_path = base_dir / "grader_log.jsonl"
    prompt_log_path = base_dir / "prompt_engineer_log.jsonl"
    # Prepare API log files for both OpenAI and Anthropic
    openai_api_log_path = base_dir / "openai_api_log.jsonl"
    anthropic_api_log_path = base_dir / "anthropic_api_log.jsonl"

    # Define grading criteria.  Each criterion has a key used in the JSON
    # evaluation and a description explaining what to look for.  Additional
    # criteria can be added to this list without changing other parts of the
    # program.  The overall score is provided by the grader based on holistic assessment.
    # Load grading criteria from YAML configuration file.
    # The file 'graders.yaml' should contain a top-level 'graders' list with objects
    # having keys: id, name, description, evaluation_criteria.
    # The 'id' field becomes the criterion name, used as dict key in grading output.
    graders_path = Path("graders.yaml")
    if not graders_path.exists():
        raise FileNotFoundError("graders.yaml file is required but was not found.")

    with graders_path.open("r") as f:
        graders_data = yaml.safe_load(f)
    grader_entries = graders_data.get("graders", [])
    if not isinstance(grader_entries, list) or not grader_entries:
        raise ValueError(
            "graders.yaml must contain a 'graders' list with at least one entry."
        )
    criteria: List[Criterion] = []
    for entry in grader_entries:
        try:
            # Map YAML 'id' field to Criterion 'name' field for consistency
            criterion_data = {
                "name": entry["id"],
                "description": entry.get("description", ""),
                "evaluation_criteria": entry.get("evaluation_criteria", ""),
            }
            crit = Criterion(**criterion_data)
            criteria.append(crit)
        except (TypeError, ValueError, KeyError) as e:
            raise ValueError(f"Invalid grader entry {entry}: {e}") from e
    # Build human-readable criteria definition for context (currently unused)
    # This could be passed to the PromptEngineer for better context awareness
    criteria_definition_lines = ["The grader uses the following axes:"]
    for crit in criteria:
        criteria_definition_lines.append(f"- {crit.name}: {crit.description}")
    criteria_definition_lines.append("The overall score is determined by the grader.")
    criteria_definition = "\n".join(criteria_definition_lines)  # Currently unused

    # Initialize the prompt engineer for the entire optimization process.
    # The PromptEngineer manages conversation state and context trimming internally.
    # PE starts with just system message, generates prompts in the main loop.
    engineer = PromptEngineer()

    # Track the version of the system prompt. Each prompt gets incremented version.
    prompt_version = 0

    # Token limits for PromptEngineer context management
    # The o3 model can handle up to 200k tokens. Context trimming is handled
    # internally by PromptEngineer to preserve reasoning token validity.
    MAX_TOKENS = 200_000
    DROP_THRESHOLD = int(0.7 * MAX_TOKENS)  # Unused: kept for reference

    # Generate initial prompt without any rollout data
    prev_reasoning, prev_function_call, current_prompt = await engineer.propose_prompt(openai_api_log_path)

    # Write initial prompt to versioned file
    prompt_version += 1
    versioned_prompt_path = base_dir / f"CLAUDE-{prompt_version:04d}.md"
    versioned_prompt_path.write_text(current_prompt)

    # Create semaphore for controlling parallel rollouts
    rollout_semaphore = asyncio.Semaphore(max_parallel_rollouts)

    async def run_single_rollout(
        task: SeedTask, rollout_id: int, iteration: int, prompt_version: int
    ) -> Tuple[CodeResult, Grade]:
        """Run a single rollout with semaphore control."""
        async with rollout_semaphore:
            # Run Claude Code agent
            code_result = await run_claude_code(
                task.prompt,
                current_prompt,
                agent_id=rollout_id,
                task_id=task.id,
                base_dir=base_dir / f"iter_{iteration}",
                anthropic_log_path=anthropic_api_log_path,
                prompt_version=prompt_version,
            )

            # Grade the result
            grade = await grade_code(code_result, criteria, openai_api_log_path)

            logger.info(
                "Rollout completed",
                task_id=task.id,
                rollout_id=rollout_id,
                iteration=iteration,
                overall_score=grade.overall_score,
            )

            return code_result, grade

    # Log experiment configuration
    logger.info(
        "Prompt optimization experiment starting",
        task_count=len(seed_tasks),
        task_ids=[task.id for task in seed_tasks],
        rollouts_per_task=rollouts_per_task,
        total_iterations=iterations,
        total_agents=len(seed_tasks) * rollouts_per_task * iterations,
        grading_criteria_count=len(criteria),
        initial_prompt=current_prompt,
    )

    for iteration in range(1, iterations + 1):
        iter_logger = logger.bind(iteration=iteration, total_iterations=iterations)
        iter_logger.info("Iteration starting")

        # Create all rollout tasks for fully parallel execution
        # Each rollout runs: Claude Code agent → grading → logging
        # Semaphore controls max concurrent rollouts to prevent resource exhaustion
        all_rollouts = []
        for task in seed_tasks:
            for rollout_id in range(rollouts_per_task):
                rollout_task = run_single_rollout(
                    task, rollout_id, iteration, prompt_version
                )
                all_rollouts.append(rollout_task)

        iter_logger.info(
            "Starting parallel rollouts",
            total_rollouts=len(all_rollouts),
            max_parallel=max_parallel_rollouts,
        )

        # Execute all rollouts in parallel with semaphore-based concurrency control
        iteration_results = await asyncio.gather(*all_rollouts)

        iter_logger.info(
            "All rollouts completed", completed_rollouts=len(iteration_results)
        )

        # Log results to JSONL files
        with inner_log_path.open("a") as f:
            for code_result, _ in iteration_results:
                record = {"iteration": iteration, **code_result.model_dump()}
                f.write(json.dumps(record) + "\n")

        with grader_log_path.open("a") as f:
            for _, grade in iteration_results:
                record = {"iteration": iteration, **grade.model_dump()}
                f.write(json.dumps(record) + "\n")

        # Display simple metrics to CLI
        overall_scores = [grade.overall_score for _, grade in iteration_results]
        avg_overall = (
            sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        )
        iter_logger.info(
            "Iteration complete", average_overall_score=round(avg_overall, 2)
        )

        # Add completed turn to PE conversation (current prompt + grades)
        grades = engineer.build_grades_message(iteration_results)
        engineer.add_result(prev_reasoning, prev_function_call, current_prompt, grades)

        # Generate next prompt using PE
        prev_reasoning, prev_function_call, new_prompt = await engineer.propose_prompt(openai_api_log_path)

        # Log the new prompt in JSONL
        with prompt_log_path.open("a") as f:
            prompt_record = {
                "iteration": iteration,
                "timestamp": datetime.utcnow().isoformat(),
                "system_prompt": new_prompt,
            }
            f.write(json.dumps(prompt_record) + "\n")

        current_prompt = new_prompt
        # Increment the prompt version and write the updated prompt to a
        # versioned file in the run directory.  This allows us to track
        # how the system prompt evolves across iterations.  Use zero-padded
        # numbering to preserve ordering.
        prompt_version += 1
        versioned_prompt_path = base_dir / f"CLAUDE-{prompt_version:04d}.md"
        versioned_prompt_path.write_text(current_prompt)

    logger.info("Optimization complete", logs_directory=str(base_dir))


def main() -> None:
    """Entry point for standalone execution."""
    parser = argparse.ArgumentParser(
        description="Parallel prompt optimization system for Claude Code agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --iterations 5 --rollouts-per-task 3
  %(prog)s --mode summary --iterations 1 --rollouts-per-task 1
        """
    )
    
    parser.add_argument(
        "--iterations", 
        type=int, 
        default=10,
        help="Number of optimization iterations (default: %(default)s)"
    )
    
    parser.add_argument(
        "--rollouts-per-task", 
        type=int, 
        default=1,
        help="Number of agent rollouts per seed task (default: %(default)s)"
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        choices=[mode.value for mode in ProcessingMode],
        default=ProcessingMode.FULL_ROLLOUTS.value,
        help="Processing mode: full_rollouts runs complete agent sessions, summary uses condensed feedback (default: %(default)s)"
    )
    
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Maximum parallel rollouts (default: %(default)s)"
    )
    
    args = parser.parse_args()
    
    # Convert string mode back to enum
    processing_mode = ProcessingMode(args.mode)
    
    # Load seed tasks from a YAML file.  The file 'seeds.yaml' should contain a
    # top-level list of objects with keys 'id' and 'prompt'.  The 'prompt'
    # field is used as the programming task.  Descriptions are ignored.
    seeds_path = Path("seeds.yaml")
    if not seeds_path.exists():
        raise FileNotFoundError("seeds.yaml file is required but was not found.")

    with seeds_path.open("r") as f:
        seeds_data = yaml.safe_load(f)
    if not isinstance(seeds_data, list) or not seeds_data:
        raise ValueError("seeds.yaml must contain a list of seed task objects.")
    seed_tasks = []
    for entry in seeds_data:
        seed_tasks.append(SeedTask(**entry))

    # Run the optimisation loop with parsed arguments
    asyncio.run(
        optimize_prompts(
            seed_tasks,
            iterations=args.iterations,
            rollouts_per_task=args.rollouts_per_task,
            processing_mode=processing_mode,
            base_output_dir="./agent_output",
            max_parallel_rollouts=args.max_parallel,
        )
    )


if __name__ == "__main__":
    main()
