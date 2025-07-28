"""
prompt_engineer_algorithm.py
=================================

This module implements a simplified version of the Prompt Engineer algorithm
described by the user.  The goal is to iteratively improve a system prompt
for a coding assistant (Claude Code) by running multiple agent rollouts on a
set of seed programming tasks, grading the generated solutions using the
OpenAI Responses API, and then using another model to propose an improved
prompt based on the previous rollouts.  Metrics and logs are written to
JSONL files for later analysis.

The design uses asynchronous functions so that multiple API calls can be
scheduled concurrently.  In a production environment you must
configure API keys for Anthropic (Claude Code) and OpenAI via
environment variables.  The script does not include any fallback or mock
behaviour; both SDKs must be installed and properly configured.

External references:
-------------------
* Anthropic Claude Code Python SDK: supports specifying a working directory
  and limiting available tools via ``ClaudeCodeOptions``.  Example usage:
  ``options = ClaudeCodeOptions(allowed_tools=["Read", "Edit", "MultiEdit"], cwd="/path/to/dir", max_turns=10)``【672369408494918†L220-L229】.
* OpenAI Responses API: provides a ``client.responses.create`` method that
  accepts ``input`` messages and an optional list of ``tools`` representing
  functions the model may call.  The API returns structured outputs which
  may include function calls that your code must execute【672369408494918†L220-L229】.  In this
  script we use the API for grading code and for proposing improved
  prompts.

Note: This script is designed for educational purposes and does not
constitute a complete production-ready implementation.  It leaves room
for replacing the placeholder logic with actual API calls once credentials
are provided.
"""

from __future__ import annotations

import asyncio
import json
import os
import structlog
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple
import shutil  # used for finding executables
from pydantic import BaseModel

# Configure structured logging
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
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

class SeedTask(BaseModel):
    id: str
    prompt: str
    description: str

class Criterion(BaseModel):
    name: str
    description: str
    evaluation_criteria: str

# Capture original PATH and binary locations before any modifications.  This
# ensures that when we create firejail wrappers for Claude Code, we refer to
# Determine absolute paths to the real ``claude`` and ``firejail`` binaries using
# the original PATH environment variable.  We capture these paths once at
# module load time so that subsequent modifications to ``os.environ['PATH']``
# (for example, when injecting wrapper scripts) do not shadow the real binaries.
# If either binary cannot be located, we immediately raise a RuntimeError
# because running the script without them is unsupported.
_ORIGINAL_PATH = os.environ.get("PATH", "")
_ORIGINAL_CLAUDE_PATH = shutil.which("claude", path=_ORIGINAL_PATH)
_ORIGINAL_FIREJAIL_PATH = shutil.which("firejail", path=_ORIGINAL_PATH)

_ORIGINAL_DOCKER_PATH = shutil.which("docker", path=_ORIGINAL_PATH)
if _ORIGINAL_CLAUDE_PATH is None:
    raise RuntimeError(
        "Claude CLI binary not found on PATH; ensure the `claude` executable is installed and available."
    )
if _ORIGINAL_DOCKER_PATH is None:
    raise RuntimeError(
        "Docker is required to run Claude Code in a container. Install Docker and ensure it is in your PATH."
    )

# -----------------------------------------------------------------------------
# Helper functions for summarising Claude Code interactions
#
# These functions encapsulate logic for extracting and formatting information
# from messages and blocks returned by the Claude Code SDK.  They produce
# concise summaries of tool invocations and text content for logging.
# -----------------------------------------------------------------------------


def _format_args_for_display(args: Any, max_len: int = 80) -> str:
    """Format tool arguments for display.

    If ``args`` is a mapping, render key:value pairs without braces or quotes.
    Otherwise, serialise to JSON or str and truncate.  Long values are
    truncated to ``max_len`` characters with an ellipsis.

    Parameters
    ----------
    args : Any
        The arguments to format.
    max_len : int
        Maximum length of each value before truncation.

    Returns
    -------
    str
        A formatted string representation of the arguments.
    """
    # Handle dict separately for key: value formatting
    if isinstance(args, dict):
        parts: List[str] = []
        for k, v in args.items():
            v_str = str(v)
            if len(v_str) > max_len:
                v_str = v_str[:max_len] + "..."
            parts.append(f"{k}: {v_str}")
        return ", ".join(parts)
    # Non-dict: attempt JSON serialisation
    try:
        arg_str = json.dumps(args)
    except Exception:
        arg_str = str(args)
    if len(arg_str) > max_len:
        arg_str = arg_str[:max_len] + "..."
    return arg_str


def _extract_text_prefix(content: Any, limit: int = 120) -> str:
    """Extract a preview of textual content.

    Parameters
    ----------
    content : Any
        The message content, which may be a string or a list of blocks.
    limit : int
        The maximum number of characters to return.

    Returns
    -------
    str
        The first ``limit`` characters of text from the content, with
        newlines replaced by spaces.
    """
    try:
        if isinstance(content, str):
            return content.strip().replace("\n", " ")[:limit]
        if isinstance(content, (list, tuple)):
            for block in content:
                if hasattr(block, "text"):
                    text = getattr(block, "text")
                    if isinstance(text, str):
                        return text.strip().replace("\n", " ")[:limit]
        return ""
    except Exception:
        return ""


def _summarise_tool_block(block: Any) -> Optional[str]:
    """Return a summary string for a tool invocation block.

    Inspect a content block for attributes indicating tool usage (``tool``, ``name``)
    and return a concise summary of the form ``ToolName(arg1: val1, arg2: val2)``.
    If no tool is detected, return ``None``.
    """
    try:
        tool_name: Optional[str] = None
        args: Any = None
        # Block may have a tool object with a name
        if hasattr(block, "tool"):
            tool_obj = getattr(block, "tool")
            tool_name = getattr(tool_obj, "name", None) or str(tool_obj)
            args = getattr(block, "arguments", None) or getattr(block, "args", None)
        elif hasattr(block, "name"):
            tool_name = getattr(block, "name")
            # For ToolUseBlock, arguments are in input/arguments/args
            if hasattr(block, "input"):
                args = getattr(block, "input")
            else:
                args = getattr(block, "arguments", None) or getattr(block, "args", None)
        if tool_name:
            if args is not None:
                arg_str = _format_args_for_display(args)
                return f"{tool_name}({arg_str})"
            return tool_name
        return None
    except Exception:
        return None


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


def format_args(args: Any, max_length: int = 80) -> str:
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
    except Exception:
        # If formatting fails, return a simple representation
        return str(args)[:max_length] + ("..." if len(str(args)) > max_length else "")


def print_message_summary(message: Any, agent_id: int) -> None:
    """Print a one-line summary of a Claude Code SDK message."""
    from claude_code_sdk import AssistantMessage, UserMessage, SystemMessage, ResultMessage
    from claude_code_sdk import TextBlock, ToolUseBlock, ToolResultBlock
    
    def truncate(text: str, limit: int = 100) -> str:
        return text[:limit] + "..." if len(text) > limit else text
    
    def clean_text(text: str) -> str:
        return text.replace('\n', ' ')
    
    if isinstance(message, SystemMessage):
        print(f"[Agent {agent_id}] SystemMessage({message.subtype})")
        
    elif isinstance(message, AssistantMessage):
        tool_uses = []
        text_content = ""
        
        for block in message.content:
            if isinstance(block, TextBlock):
                text_content = block.text
            elif isinstance(block, ToolUseBlock):
                args = ', '.join(f'{k}={truncate(str(v), 30)}' for k, v in block.input.items())
                tool_uses.append(f"{block.name}({args})")
            elif isinstance(block, ToolResultBlock):
                content = block.content if isinstance(block.content, str) else str(block.content)
                print(f"[Agent {agent_id}] ToolResult({block.tool_use_id[:8]}) - \"{clean_text(truncate(content, 60))}\"")
        
        if tool_uses:
            print(f"[Agent {agent_id}] {', '.join(tool_uses)}")
        elif text_content:
            print(f'[Agent {agent_id}] AssistantMessage - "{clean_text(truncate(text_content))}"')
        # Note: ToolResultBlock printing is handled above in the loop
            
    elif isinstance(message, UserMessage):
        # UserMessage.content is just a string according to the SDK
        print(f'[Agent {agent_id}] UserMessage - "{clean_text(truncate(message.content))}"')
                    
    elif isinstance(message, ResultMessage):
        cost_str = f"${message.total_cost_usd}" if message.total_cost_usd else "unknown"
        print(f"[Agent {agent_id}] ResultMessage (duration: {message.duration_ms}ms, cost: {cost_str}, error: {message.is_error})")
        
    else:
        print(f"[Agent {agent_id}] {type(message).__name__}")


def extract_text_prefix(text: str, limit: int = 120) -> str:
    """Extract the first ``limit`` characters from a block of text.

    Newlines are replaced with spaces to provide a single‑line preview.

    Parameters
    ----------
    text : str
        The text to extract from.
    limit : int
        Maximum number of characters to return.

    Returns
    -------
    str
        The extracted prefix.
    """
    try:
        if not isinstance(text, str):
            text = str(text)
        single_line = text.replace("\n", " ").strip()
        return single_line[:limit]
    except Exception:
        return ""


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
            except Exception:
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
            except Exception:
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
    except Exception:
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
            except Exception:
                pass
        return None
    except Exception:
        return None


# Import the Claude Code SDK and OpenAI library.  If these imports fail,
# the script should terminate rather than falling back to mock behaviour.
# Import Claude Code SDK from the official claude_code_sdk package.  The
# repository is available at https://github.com/anthropics/claude-code-sdk-python.
# We import the query function and ClaudeCodeOptions to interact with the
# Claude Code service.  The query function handles asynchronous streaming of
# events from the model, and ClaudeCodeOptions configures the agent.
from claude_code_sdk import query as claude_query
from claude_code_sdk import ClaudeCodeOptions
from openai import OpenAI
import tiktoken


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
    "a single argument `prompt` containing your improved system prompt. Do not output anything else."
)

# The initial user message given to the prompt engineer.  It embeds the
# starting system prompt and a description of the grading criteria.  It is
# formatted with initial_prompt and criteria_definition.
PROMPT_ENGINEER_INITIAL_USER_MESSAGE_TEMPLATE = (
    "Initial system prompt:\n{initial_prompt}\n\n{criteria_definition}"
)

# Template for summarising rollouts to the prompt engineer.  It includes the
# current prompt and the detailed rollout summaries.  It instructs the model
# to propose a better system prompt without extra commentary.
PROMPT_ENGINEER_ROLLOUT_SUMMARY_TEMPLATE = """
Current system prompt:
{current_prompt}

Here are the latest rollouts and their grades:
{rollouts_text}

Please identify the failures or shortcomings of the current system prompt based on these rollouts.  Suggest a revised system prompt that addresses these issues and improves performance on the grading axes.  Respond only with the new system prompt without any additional commentary.
"""

# Template for the grading evaluation prompt.  It describes the task, lists
# all submitted code files, enumerates the grading axes, and specifies the
# required JSON output schema.  It instructs the model to compute the
# overall score as the average of the axis scores and to provide a rationale.
EVALUATION_PROMPT_TEMPLATE = """
You are an expert Python instructor and code reviewer.  A student has submitted code for the following task:
{task}

Here are the code files:
{combined_code}

Please evaluate the submission on the following axes:

{axes_text}

Return your evaluation as a JSON object with the following structure:
{json_structure}

Compute the overall score as the average of the axis scores and provide a brief rationale explaining the overall grade.
"""

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
        if hasattr(response, "model_dump"):
            response_data = response.model_dump()
        elif hasattr(response, "dict"):
            response_data = response.dict()
        elif hasattr(response, "json"):
            response_data = json.loads(response.json())
        else:
            response_data = str(response)
    except Exception:
        response_data = str(response)
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
    except Exception:
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
    list.  The overall score is computed as the average of the axis scores.
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

    # Ensure a local settings directory exists for Claude Code.  We create
    # `.claude/settings.local.json` with an empty JSON object so that each
    # agent's session starts with a clean configuration.  The use of
    # settings.local.json allows per‑project overrides in Claude Code.
    try:
        claude_settings_dir = work_dir / ".claude"
        claude_settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = claude_settings_dir / "settings.local.json"
        # Write an empty JSON object if the file does not already exist or is empty.
        if not settings_file.exists() or not settings_file.read_text().strip():
            settings_file.write_text("{}")
    except Exception:
        # Silently ignore any errors creating settings; they are optional.
        pass

    # Print the working directory for this agent to the console so that users
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
    os.environ["BASH_MAX_TIMEOUT_MS"] = "30000"
    
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
            options.model_dump() if hasattr(options, "model_dump") else str(options)
        ),
    }
    # Log the request before sending
    log_anthropic_request_event(anthropic_log_path, anthropic_request, "request_sent")
    
    # Debug: Print what command would be generated
    agent_logger.info("Starting Claude Code session")
    # Import the correct message types from the SDK and use ClaudeSDKClient for streaming mode
    from claude_code_sdk import AssistantMessage, UserMessage, SystemMessage, ResultMessage
    from claude_code_sdk import TextBlock, ToolUseBlock, ToolResultBlock, ClaudeSDKClient
    from dataclasses import asdict
    
    # Use ClaudeSDKClient to force streaming mode instead of print mode
    async with ClaudeSDKClient(options=options) as client:
        await client.query(task)
        async for message in client.receive_messages():
            # Log each event from the Claude Code API
            log_anthropic_request_event(anthropic_log_path, anthropic_request, message)
            
            # Store the message using dataclasses.asdict() for proper serialization
            message_sequence.append(asdict(message))

            # Print message summary
            print_message_summary(message, agent_id)
            
            # Break out of the loop when we receive a ResultMessage (conversation is complete)
            if isinstance(message, ResultMessage):
                agent_logger.info("Session completed", 
                                duration_ms=message.duration_ms, 
                                cost_usd=message.total_cost_usd, 
                                is_error=message.is_error)
                break

    # After the conversation completes, gather all files in the agent directory
    files_info: List[Dict[str, str]] = []
    for file_path in work_dir.rglob("*"):
        if file_path.is_file() and file_path.name != "CLAUDE.md":
            relative = file_path.relative_to(work_dir).as_posix()
            try:
                content = file_path.read_text()
            except Exception:
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
        A list of grading facets to evaluate.  Each facet will appear as a
        property in the function schema.
    openai_log_path : Path
        Path to a JSONL file where requests and responses to the OpenAI API
        will be logged.

    Returns
    -------
    Grade
        A dataclass containing the grading information.
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
    grade_logger = logger.bind(agent_id=result.agent_id, task_id=getattr(result, 'task_id', 'unknown'))
    grade_logger.info("Making OpenAI grading call")
    
    response = client.responses.create(
        model="o3",
        input=input_messages,
        tools=[grading_tool],
        tool_choice={"type": "function", "name": "submit_grades"},
    )
    # Log request and response
    log_openai_request_response(openai_log_path, openai_request, response)
    grade_logger.info("OpenAI grading completed")
    
    # Extract and log grading results before processing
    args_str = (
        call.arguments if hasattr(call, "arguments") else call.get("arguments")
    )
    if isinstance(args_str, str):
        grades_data = json.loads(args_str)
        facet_results = {}
        for facet_name, facet_data in grades_data.items():
            if isinstance(facet_data, dict) and "score" in facet_data:
                score = facet_data.get("score", 0)
                rationale = facet_data.get("rationale", "")
                facet_results[facet_name] = {"score": score, "rationale": rationale}
        
        grade_logger.info("Grading results", facets=facet_results)

    # Extract the function_call item from the response.  The output may
    # include reasoning items before the function call, so we iterate to find
    # the first item with type == "function_call".  Items may be Pydantic
    # models or dictionaries.
    call = None
    for item in response.output or []:
        # Determine item type
        item_type = None
        try:
            if hasattr(item, "type"):
                item_type = item.type
            elif isinstance(item, dict):
                item_type = item.get("type")
        except Exception:
            item_type = None
        if item_type == "function_call":
            call = item
            break
    if call is None:
        raise RuntimeError("The grader did not call submit_grades as required.")
    # Determine the function name
    try:
        call_name = call.name if hasattr(call, "name") else call.get("name")
    except Exception:
        call_name = None
    if call_name != "submit_grades":
        raise RuntimeError(f"Unexpected function name: {call_name}")
    # Extract the arguments string
    try:
        args_str = (
            call.arguments if hasattr(call, "arguments") else call.get("arguments")
        )
    except Exception:
        args_str = None
    if not isinstance(args_str, str):
        raise ValueError(
            f"Could not retrieve arguments from submit_grades call: {call}"
        )
    # Parse the JSON string into a dict
    try:
        result_data = json.loads(args_str)
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse grading JSON: {args_str}")

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


async def propose_new_prompt(
    messages: List[Dict[str, Any]],
    reasoning_items: List[Dict[str, Any]],
    current_prompt: str,
    new_rollouts: List[Tuple[CodeResult, Grade]],
    openai_log_path: Path,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Propose an improved system prompt based on cumulative rollouts.

    The prompt engineer maintains a persistent conversation across iterations.  Each
    time this function is called, it appends a new user message describing the
    latest rollouts and asks the assistant to generate an improved system prompt.

    Parameters
    ----------
    messages : list of dict
        The current conversation history between the prompt engineer and the model.
    current_prompt : str
        The system prompt currently in use by the coding agents.
    new_rollouts : list of tuples (CodeResult, Grade)
        The rollouts and their associated grades from the most recent iteration.

    Returns
    -------
    tuple (str, list)
        A pair containing the improved prompt and the updated conversation history.
    """
    # Build detailed summaries of the new rollouts.  Each rollout summary
    # includes the task, scores, rationales, the full conversation log as
    # JSON lines, and the generated code files.  These summaries will be
    # appended to the conversation as a function_call_output so the model can
    # analyse them when producing the next prompt.
    rollout_summaries: List[str] = []
    for code_result, grade in new_rollouts:
        # Serialize full message sequence for this rollout
        message_lines: List[str] = []
        for evt in code_result.messages:
            message_lines.append(json.dumps(evt))
        messages_text = "\n".join(message_lines)
        # Serialize full code by listing each file
        code_lines: List[str] = []
        for file_info in code_result.files:
            code_lines.append(f"### {file_info['path']}\n{file_info['content']}")
        full_code = "\n\n".join(code_lines)
        # Build dynamic score and rationale lines based on the axes present in the grade
        score_parts: List[str] = []
        rationale_parts: List[str] = []
        for key, score in grade.axis_scores.items():
            score_parts.append(f"  {key}={score}")
        for key, rationale in grade.axis_rationales.items():
            rationale_parts.append(f"  {key}: {rationale}")
        score_str = ", ".join(score_parts)
        rationale_str = "\n".join(rationale_parts)
        # Compose the summary for this rollout
        rollout_summaries.append(
            f"ROLLOUT for task: {code_result.task}\n"
            f"Agent {code_result.agent_id} scores:\n{score_str}, overall={grade.overall_score}\n"
            f"Rationales:\n{rationale_str}\n  overall: {grade.overall_rationale}\n"
            f"Conversation log (JSON lines):\n{messages_text}\n"
            f"Generated code files:\n{full_code}\n"
        )
    summary_text = "\n".join(rollout_summaries).strip()

    # Determine the call_id of the last submit_prompt call.  We need this to
    # attach our summary as the output of that call.  Search the messages in
    # reverse order for the most recent item with type "function_call" and name
    # "submit_prompt".  If none is found (only possible for the initial synthetic
    # call), use the call_id of the synthetic seed.
    last_call_id = None
    for m in reversed(messages):
        if m.get("type") == "function_call" and m.get("name") == "submit_prompt":
            last_call_id = m.get("call_id")
            break
    if last_call_id is None:
        # Fallback to synthetic call id if not found
        last_call_id = "synthetic_0"

    # Append a function_call_output summarising the new rollouts.  This message
    # provides the model with the full results of the last prompt.  We do not
    # include any additional commentary or instructions here; the system
    # message already tells the model how to behave.
    messages.append(
        {
            "type": "function_call_output",
            "call_id": last_call_id,
            "output": summary_text,
        }
    )

    # Prepare the input for the model by combining conversation messages and
    # accumulated reasoning items.  The model will read the rollouts summary
    # from the function_call_output and produce a new prompt via a call to
    # submit_prompt.
    input_items: List[Dict[str, Any]] = []
    input_items.extend(messages)
    input_items.extend(reasoning_items)

    client = OpenAI()
    # Define the submit_prompt function for the model.  We enforce strict
    # schema compliance via "strict": True.
    tools = [
        {
            "type": "function",
            "name": "submit_prompt",
            "description": "Submit an improved system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The revised system prompt for the coding assistant.",
                    }
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]
    # Log the OpenAI request
    openai_request = {
        "model": "o3",
        "input": input_items,
        "tools": tools,
        "tool_choice": {"type": "function", "name": "submit_prompt"},
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 4000,
        "include": ["reasoning.encrypted_content"],
    }
    response = client.responses.create(
        model="o3",
        input=input_items,
        tools=tools,
        tool_choice={"type": "function", "name": "submit_prompt"},
        reasoning={"effort": "medium"},
        max_output_tokens=4000,
        include=["reasoning.encrypted_content"],
    )
    # Log the response
    log_openai_request_response(openai_log_path, openai_request, response)

    # Extract reasoning items and function calls from the response.  The API
    # returns reasoning items before function calls.  Items may be Pydantic
    # models or dictionaries.  We convert them to dicts when appending to
    # reasoning_items to avoid mixing object types.
    new_reasoning_items: List[Dict[str, Any]] = []
    for item in response.output or []:
        # Determine item type
        item_type = None
        try:
            if hasattr(item, "type"):
                item_type = item.type
            elif isinstance(item, dict):
                item_type = item.get("type")
        except Exception:
            item_type = None
        if item_type == "reasoning":
            # Convert to dictionary for consistency
            try:
                item_dict = (
                    item.model_dump()
                    if hasattr(item, "model_dump")
                    else (item.dict() if hasattr(item, "dict") else item)
                )
            except Exception:
                item_dict = item
            new_reasoning_items.append(item_dict)
        elif item_type in {"function_call", "function_call_output"}:
            try:
                item_dict = (
                    item.model_dump()
                    if hasattr(item, "model_dump")
                    else (item.dict() if hasattr(item, "dict") else item)
                )
            except Exception:
                item_dict = item
            new_reasoning_items.append(item_dict)

    # Find the first function_call item; this should be our submit_prompt call
    call_item = None
    for item in response.output or []:
        item_type = None
        try:
            if hasattr(item, "type"):
                item_type = item.type
            elif isinstance(item, dict):
                item_type = item.get("type")
        except Exception:
            item_type = None
        if item_type == "function_call":
            call_item = item
            break
    if call_item is None:
        raise RuntimeError(
            "Prompt engineer model did not call submit_prompt as expected."
        )
    # Extract function name
    try:
        call_name = (
            call_item.name if hasattr(call_item, "name") else call_item.get("name")
        )
    except Exception:
        call_name = None
    if call_name != "submit_prompt":
        raise RuntimeError(f"Unexpected function name: {call_name}")
    # Extract call_id
    try:
        call_id = (
            call_item.call_id
            if hasattr(call_item, "call_id")
            else call_item.get("call_id")
        )
    except Exception:
        call_id = None
    # Extract arguments string
    try:
        arguments_str = (
            call_item.arguments
            if hasattr(call_item, "arguments")
            else call_item.get("arguments")
        )
    except Exception:
        arguments_str = None
    if not isinstance(arguments_str, str):
        raise ValueError(
            f"Could not retrieve arguments from submit_prompt call: {call_item}"
        )
    try:
        args_dict = json.loads(arguments_str)
    except json.JSONDecodeError:
        raise ValueError(f"Could not parse submit_prompt arguments: {arguments_str}")
    new_prompt = args_dict.get("prompt", "").strip()
    # Convert the call_item to a dict for storing in the conversation
    try:
        call_dict = (
            call_item.model_dump()
            if hasattr(call_item, "model_dump")
            else (call_item.dict() if hasattr(call_item, "dict") else call_item)
        )
    except Exception:
        call_dict = call_item
    messages.append(call_dict)
    # Acknowledge the prompt by appending a function_call_output.  We do not
    # repeat the prompt itself; the presence of the call in the messages is
    # sufficient for the model to incorporate it into its reasoning.
    messages.append(
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": "Prompt accepted.",
        }
    )
    # Return the new prompt, updated conversation, and new reasoning items
    return new_prompt, messages, new_reasoning_items


async def optimize_prompts(
    seed_tasks: List[str],
    initial_prompt: str,
    iterations: int = 3,
    rollouts_per_task: int = 2,
    base_output_dir: str = "./agent_output",
) -> None:
    """Run the prompt optimisation loop.

    This is the main entry point for running multiple iterations of the algorithm.  It
    repeatedly executes batches of Claude Code agents on the seed tasks, grades
    the generated solutions, updates the system prompt using a prompt engineer,
    and logs results to CSV files.

    Parameters
    ----------
    seed_tasks : list of str
        The programming tasks to use as the benchmark for optimisation.
    initial_prompt : str
        The initial system prompt used for all Claude Code agents.
    iterations : int, optional
        The number of optimisation iterations to perform (default 3).
    rollouts_per_task : int, optional
        The number of Claude Code agents to sample per task in each iteration (default 2).
    base_output_dir : str, optional
        Base directory where agent working directories and logs will be stored.
    """
    # Create a unique prefix for this run to avoid collisions with previous
    # executions.  The prefix is based on the current UTC timestamp.  All
    # working directories and logs for this run will be stored under
    # base_output_dir / run_prefix.
    run_prefix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = (Path(base_output_dir) / run_prefix).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Run] Using unique run directory: {base_dir}")

    # ---------------------------------------------------------------------
    # Docker wrapper setup
    #
    # Use external docker wrapper script as a transparent claude proxy
    wrapper_dir = base_dir / "bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_script = wrapper_dir / "claude"
    
    # Copy the external wrapper script
    external_wrapper = Path(__file__).parent / "docker_claude_wrapper.sh"
    shutil.copy2(external_wrapper, wrapper_script)
    wrapper_script.chmod(0o755)
    
    # Prepend wrapper directory to PATH
    os.environ["PATH"] = f"{wrapper_dir}:{_ORIGINAL_PATH}"
    print(f"[Run] Docker wrapper installed at {wrapper_script}, PATH updated")

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
    # program.  The overall score is computed as the average of these axes.
    # Load grading facets (criteria) from an external YAML configuration.  The
    # file 'graders.yaml' should contain a top-level key 'graders' whose value
    # is a list of objects with keys: id, name, description, evaluation_criteria.
    # The 'id' field is used as the dict key in the grading output, while
    # 'description' and 'evaluation_criteria' become the Pydantic fields.  If
    # the YAML file cannot be loaded, an exception will propagate.
    graders_path = Path("graders.yaml")
    if not graders_path.exists():
        raise FileNotFoundError("graders.yaml file is required but was not found.")
    import yaml  # Imported here to avoid dependency if YAML not needed elsewhere

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
            # Map 'id' field to 'name' for Criterion model
            criterion_data = {
                "name": entry["id"],
                "description": entry.get("description", ""),
                "evaluation_criteria": entry.get("evaluation_criteria", "")
            }
            crit = Criterion(**criterion_data)
            criteria.append(crit)
        except Exception as e:
            raise ValueError(f"Invalid grader entry {entry}: {e}")
    # Build a human-readable definition of the criteria to share with the prompt engineer
    criteria_definition_lines = ["The grader uses the following axes:"]
    for crit in criteria:
        criteria_definition_lines.append(f"- {crit.name}: {crit.description}")
    criteria_definition_lines.append("The overall score is determined by the grader.")
    criteria_definition = "\n".join(criteria_definition_lines)

    # Initialise the prompt engineer conversation.  The system message instructs
    # the model to call submit_prompt with improved prompts whenever rollouts
    # and grades are shown.  There is no user message; instead we start
    # with a synthetic function_call representing the initial prompt.
    current_prompt = initial_prompt
    # Track the version of the system prompt.  The initial prompt is version 0,
    # and each time we obtain a new prompt from the prompt engineer, we
    # increment this counter.  This version number is used to name the
    # corresponding CLAUDE-XXXX.md file for each iteration.
    prompt_version = 0
    pe_messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": PROMPT_ENGINEER_SYSTEM_MESSAGE,
        },
        {
            # Synthetic function call seeding the loop with the initial prompt
            "type": "function_call",
            "name": "submit_prompt",
            "call_id": "synthetic_0",
            "arguments": json.dumps({"prompt": initial_prompt}),
        },
    ]
    # List to store reasoning items returned by the model.  It starts empty
    # because the synthetic call does not generate reasoning.
    pe_reasoning_items: List[Dict[str, Any]] = []

    # Function to estimate token count for the conversation using tiktoken
    def count_tokens(msgs: List[Dict[str, Any]], model: str = "gpt-4.1") -> int:
        """Estimate the number of tokens used by the given messages."""
        enc = tiktoken.encoding_for_model(model)
        tokens = 0
        for m in msgs:
            # Compute token count based on available fields.  The Responses API
            # stores text in 'content' for system/user/assistant messages,
            # 'arguments' for function_call items, and 'output' for
            # function_call_output items.  We sum tokens from all these
            # fields if present to approximate the true context length.
            if "content" in m:
                tokens += len(enc.encode(str(m["content"])))
            if "arguments" in m:
                tokens += len(enc.encode(str(m["arguments"])))
            if "output" in m:
                tokens += len(enc.encode(str(m["output"])))
        return tokens

    # Set token budgets.  The model can handle up to 200k tokens.  We trigger
    # dropoff when the conversation exceeds 70% of that capacity.
    MAX_TOKENS = 200_000
    DROP_THRESHOLD = int(0.7 * MAX_TOKENS)

    # Save the initial prompt in the run directory for reference.  The version is 0.
    initial_prompt_path = base_dir / f"CLAUDE-{prompt_version:04d}.md"
    initial_prompt_path.write_text(initial_prompt)
    
    # Log experiment configuration
    logger.info("Prompt optimization experiment starting",
                task_count=len(seed_tasks),
                task_ids=[task.id for task in seed_tasks],
                rollouts_per_task=rollouts_per_task,
                total_iterations=iterations,
                total_agents=len(seed_tasks) * rollouts_per_task * iterations,
                grading_criteria_count=len(criteria),
                initial_prompt=current_prompt)

    for iteration in range(1, iterations + 1):
        iter_logger = logger.bind(iteration=iteration, total_iterations=iterations)
        iter_logger.info("Iteration starting")
        iteration_results: List[Tuple[CodeResult, Grade]] = []

        # Run rollouts for each task
        for task_idx, task in enumerate(seed_tasks):
            task_id = task.id  # Use the readable task ID from YAML
            task_prompt = task.prompt
            task_logger = logger.bind(task_id=task_id, iteration=iteration)
            
            # Launch multiple agents concurrently for the same task.  Pass the
            # current prompt version to run_claude_code so that the prompt
            # file is saved with the appropriate version number.
            tasks = [
                run_claude_code(
                    task_prompt,
                    current_prompt,
                    agent_id=i,
                    task_id=task_id,
                    base_dir=base_dir / f"iter_{iteration}",
                    anthropic_log_path=anthropic_api_log_path,
                    prompt_version=prompt_version,
                )
                for i in range(rollouts_per_task)
            ]
            code_results = await asyncio.gather(*tasks)
            task_logger.info("Code generation completed", agent_count=len(code_results))
            
            # Grade each result
            task_logger.info("Grading starting")
            grade_tasks = [
                grade_code(result, criteria, openai_api_log_path)
                for result in code_results
            ]
            grades = await asyncio.gather(*grade_tasks)
            task_logger.info("Grading completed")
            # Append to iteration summary
            iteration_results.extend(zip(code_results, grades))

            # Log inner agent results to JSONL
            with inner_log_path.open("a") as f:
                for result in code_results:
                    record = {"iteration": iteration, **result.model_dump()}
                    f.write(json.dumps(record) + "\n")
            # Log grading results to JSONL
            with grader_log_path.open("a") as f:
                for grade in grades:
                    record = {"iteration": iteration, **grade.model_dump()}
                    f.write(json.dumps(record) + "\n")

        # Display simple metrics to CLI
        overall_scores = [grade.overall_score for _, grade in iteration_results]
        avg_overall = (
            sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        )
        print(f"Average overall score: {avg_overall:.2f}")

        # Update the system prompt using the prompt engineer with cumulative messages
        new_prompt, pe_messages, pe_reasoning_items = await propose_new_prompt(
            pe_messages,
            pe_reasoning_items,
            current_prompt,
            iteration_results,
            openai_api_log_path,
        )

        # After obtaining a new prompt, report current context length and
        # truncate the conversation if it exceeds the drop threshold.
        before_tokens = count_tokens(pe_messages)
        drop_occurred = False
        if before_tokens > DROP_THRESHOLD and len(pe_messages) > 5:
            # Keep the system message and the last two iterations.  Each iteration
            # appends approximately three messages: a function_call_output summarising
            # the rollouts, the assistant's function_call submitting the new
            # prompt, and a function_call_output acknowledging the prompt.  To
            # preserve the last two iterations, keep the last six messages plus
            # the system message at index 0.
            pe_messages = [pe_messages[0]] + pe_messages[-6:]
            # For reasoning models, drop any accumulated reasoning items when we
            # truncate the context.  This prevents stale reasoning tokens from
            # polluting the context after old messages are removed.  Clear the
            # list in-place to preserve the original reference.
            pe_reasoning_items.clear()
            drop_occurred = True
        after_tokens = count_tokens(pe_messages)
        # Log context length and whether drop occurred
        if drop_occurred:
            print(
                f"[PromptEngineer] Context trimmed: {before_tokens} → {after_tokens} tokens (dropped older rollouts)"
            )
        else:
            print(f"[PromptEngineer] Context length: {before_tokens} tokens")

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

    print("\nOptimization complete.  Logs have been saved to:", base_dir)


def main() -> None:
    """Entry point for standalone execution."""
    # Load seed tasks from a YAML file.  The file 'seeds.yaml' should contain a
    # top-level list of objects with keys 'id' and 'prompt'.  The 'prompt'
    # field is used as the programming task.  Descriptions are ignored.
    seeds_path = Path("seeds.yaml")
    if not seeds_path.exists():
        raise FileNotFoundError("seeds.yaml file is required but was not found.")
    import yaml  # Imported here to avoid dependency if YAML not needed elsewhere

    with seeds_path.open("r") as f:
        seeds_data = yaml.safe_load(f)
    if not isinstance(seeds_data, list) or not seeds_data:
        raise ValueError("seeds.yaml must contain a list of seed task objects.")
    seed_tasks = []
    for entry in seeds_data:
        try:
            seed_task = SeedTask(**entry)
            seed_tasks.append(seed_task)
        except Exception as e:
            raise ValueError(f"Invalid seed task entry {entry}: {e}")

    # Initial system prompt instructing the coding assistant how to behave.  The assistant
    # is described simply as a helpful coding assistant; more detailed guidance will be
    # provided through iterative prompt optimisation.
    initial_prompt = "You are a helpful coding assistant."

    # Run the optimisation loop.  Adjust iterations and rollouts per task as desired.
    asyncio.run(
        optimize_prompts(
            seed_tasks,
            initial_prompt,
            iterations=3,
            rollouts_per_task=1,
            base_output_dir="./agent_output",
        )
    )


if __name__ == "__main__":
    main()

