"""Declarative step classes for test agent state machines.

See docs/test_scenario_steps.md for detailed usage guide.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Protocol, TypeVar

from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, TypeAdapter

from adgn.mcp._shared.calltool import extract_structured_content
from adgn.mcp._shared.constants import APPROVAL_ADMIN_MOUNT_PREFIX, UI_MOUNT_PREFIX
from adgn.mcp._shared.naming import parse_tool_name
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.approval_policy.engine import SetPolicyTextArgs
from adgn.mcp.exec.models import BaseExecResult, Exited, Killed, TimedOut, TruncatedStream
from adgn.mcp.testing.simple_servers import ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput
from adgn.mcp.ui.server import SendMessageInput
from adgn.openai_utils.model import FunctionCallItem, FunctionCallOutputItem, ResponsesRequest, ResponsesResult
from adgn.props.docker_env import DOCKER_MOUNT_PREFIX
from tests.support.assertions import assert_and_extract, assert_last_call
from tests.support.responses import ResponsesFactory

logger = logging.getLogger(__name__)

# Directory for bootstrap output dumps (under tests/props/)
BOOTSTRAP_DUMPS_DIR = Path(__file__).parent.parent / "props" / "bootstrap_dumps"

T = TypeVar("T", bound=BaseModel)


def _is_runtime_exec_tool(tool_name: str) -> bool:
    """Check if tool_name is a runtime exec tool (e.g., runtime_exec)."""
    try:
        prefix, tool = parse_tool_name(tool_name)
        return prefix == DOCKER_MOUNT_PREFIX and tool == "exec"
    except ValueError:
        return False


def _get_stream_size(stream: str | TruncatedStream) -> int:
    """Get the byte size of a stdout/stderr stream.

    For TruncatedStream, uses total_bytes (original size before truncation).
    For str, uses UTF-8 encoded length.
    """
    if isinstance(stream, TruncatedStream):
        return stream.total_bytes
    return len(stream.encode("utf-8"))


def _get_stream_text(stream: str | TruncatedStream) -> str:
    """Get the text content of a stdout/stderr stream."""
    if isinstance(stream, TruncatedStream):
        return stream.truncated_text
    return stream


def _dump_bootstrap_output(exec_result: BaseExecResult, cmd_args: str, test_name: str | None = None) -> Path:
    """Dump bootstrap init output to a file for inspection.

    Creates files in tests/bootstrap_dumps/<agent_type>_<timestamp>.txt

    Args:
        exec_result: The parsed exec result containing stdout/stderr
        cmd_args: Command arguments string (used to infer agent type)
        test_name: Optional test name for the filename

    Returns:
        Path to the dump file
    """
    BOOTSTRAP_DUMPS_DIR.mkdir(parents=True, exist_ok=True)

    name = test_name or "unknown"
    stdout_path = BOOTSTRAP_DUMPS_DIR / f"{name}.stdout"
    stderr_path = BOOTSTRAP_DUMPS_DIR / f"{name}.stderr"

    stdout_path.write_text(_get_stream_text(exec_result.stdout))
    stderr_path.write_text(_get_stream_text(exec_result.stderr))

    logger.info("Bootstrap output dumped to: %s, %s", stdout_path, stderr_path)
    return stdout_path


def assert_bootstrap_exec_success(req: ResponsesRequest, *, test_name: str | None = None) -> None:
    """Assert all runtime exec calls in the request completed with exit code 0.

    Bootstrap commands run BEFORE the test's step sequence. If any bootstrap command
    failed or timed out, the test should fail immediately with clear diagnostics.

    This function:
    1. Builds a map of call_id -> tool_name from FunctionCallItem entries
    2. Finds FunctionCallOutputItem entries for runtime_exec calls (via parse_tool_name)
    3. Parses outputs as BaseExecResult and validates exit status
    4. Logs bootstrap output sizes for each command
    5. Dumps bootstrap output to tests/bootstrap_dumps/ for inspection

    Args:
        req: The ResponsesRequest containing bootstrap calls and outputs
        test_name: Optional test name for the dump filename (e.g., "test_critic_http_mode_zero_issues")

    Raises:
        AssertionError: If any runtime exec command failed or timed out, with details
            about which command failed and why.
    """
    # Try to get test name from pytest if not provided
    if test_name is None:
        raw = os.environ.get("PYTEST_CURRENT_TEST", "")
        # Format: "path/to/test.py::test_name[param] (call)" - extract just test_name
        test_name = raw.split("::")[-1].split("[")[0].split(" ")[0]

    # Build call_id -> tool_name map from FunctionCallItem entries
    call_id_to_tool: dict[str, str] = {}
    call_id_to_args: dict[str, str] = {}
    for item in req.input:
        if isinstance(item, FunctionCallItem):
            call_id_to_tool[item.call_id] = item.name
            # Store full arguments for dump
            args_str = item.arguments if isinstance(item.arguments, str) else json.dumps(item.arguments)
            call_id_to_args[item.call_id] = args_str

    failures: list[str] = []
    bootstrap_sizes: list[tuple[str, int, int]] = []  # (cmd_preview, stdout_bytes, stderr_bytes)

    for item in req.input:
        if not isinstance(item, FunctionCallOutputItem):
            continue

        call_id = item.call_id
        tool_name = call_id_to_tool.get(call_id)

        # Only check runtime exec calls (tool name: runtime_exec)
        if tool_name is None or not _is_runtime_exec_tool(tool_name):
            continue

        output_str = item.output
        if output_str is None:
            failures.append(f"Runtime exec call has no output (tool={tool_name}, call_id={call_id})")
            continue

        # Parse as CallToolResult and then as BaseExecResult
        try:
            result_dict = json.loads(output_str)
            result = TypeAdapter(mcp_types.CallToolResult).validate_python(result_dict)
            exec_result = extract_structured_content(result, BaseExecResult)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # If it's a runtime exec call but can't be parsed, that's suspicious
            failures.append(
                f"Failed to parse runtime exec result (tool={tool_name}, call_id={call_id}):\n"
                f"  parse error: {e}\n"
                f"  raw output: {output_str[:500]!r}"
            )
            continue

        # Collect output sizes for logging
        stdout_bytes = _get_stream_size(exec_result.stdout)
        stderr_bytes = _get_stream_size(exec_result.stderr)
        cmd_args = call_id_to_args.get(call_id, "unknown")
        bootstrap_sizes.append((cmd_args[:50], stdout_bytes, stderr_bytes))

        # Dump bootstrap output to file for inspection
        _dump_bootstrap_output(exec_result, cmd_args, test_name=test_name)

        # Check exit status - dump full model on failure for diagnostics
        if isinstance(exec_result.exit, TimedOut):
            failures.append(
                f"Bootstrap command TIMED OUT (tool={tool_name}, call_id={call_id}):\n"
                f"  {exec_result.model_dump_json(indent=2)}"
            )
        elif isinstance(exec_result.exit, Exited):
            if exec_result.exit.exit_code != 0:
                failures.append(
                    f"Bootstrap command FAILED with exit_code={exec_result.exit.exit_code} "
                    f"(tool={tool_name}, call_id={call_id}):\n"
                    f"  {exec_result.model_dump_json(indent=2)}"
                )
        elif isinstance(exec_result.exit, Killed):
            failures.append(
                f"Bootstrap command was KILLED (tool={tool_name}, call_id={call_id}):\n"
                f"  {exec_result.model_dump_json(indent=2)}"
            )

    # Log bootstrap output sizes
    if bootstrap_sizes:
        total_stdout = sum(s[1] for s in bootstrap_sizes)
        total_stderr = sum(s[2] for s in bootstrap_sizes)
        logger.info(
            "Bootstrap output sizes: %d commands, %d bytes stdout, %d bytes stderr (total: %d bytes)",
            len(bootstrap_sizes),
            total_stdout,
            total_stderr,
            total_stdout + total_stderr,
        )
        for cmd_preview, stdout_bytes, stderr_bytes in bootstrap_sizes:
            logger.debug("  %s: stdout=%d, stderr=%d", cmd_preview, stdout_bytes, stderr_bytes)

    if failures:
        raise AssertionError(
            f"Bootstrap runtime exec commands failed ({len(failures)} failures):\n\n" + "\n\n".join(failures)
        )


# Test constants (not re-exported - use server class constants directly)
FAIL_TEST_TOOL_NAME = "fail"  # Used in test fixtures


class EmptyArgs(BaseModel):
    """Empty arguments for zero-parameter MCP tools.

    Use this instead of tool-specific empty input models for consistency across tests.
    """

    model_config = ConfigDict(extra="forbid")


class Step(Protocol):
    """Protocol for step objects that can be executed in sequence."""

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult: ...


@dataclass
class AssertBootstrapSuccess:
    """Assert all bootstrap docker exec commands succeeded.

    Use as the FIRST step in any test that uses bootstrap. Validates that all
    docker exec commands in the transcript completed with exit code 0.

    This step does not consume a mock response - it only validates the bootstrap
    phase completed successfully before the step sequence begins.
    """

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_bootstrap_exec_success(req)
        # Return a minimal assistant message to continue the conversation
        return factory.make_assistant_message("Bootstrap validated successfully")


@dataclass
class MakeCall:
    """Initial turn: make a tool call."""

    server: MCPMountPrefix
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class MakeCallWithBootstrapValidation(MakeCall):
    """Initial turn: validate bootstrap succeeded, then make a tool call.

    Use this instead of MakeCall when the test has bootstrap docker exec commands
    that should be validated before the first agent tool call.
    """

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_bootstrap_exec_success(req)
        return super().execute(req, factory)


@dataclass
class CheckThenCall:
    """Assert previous tool completed, then call next."""

    expected_tool: str
    server: MCPMountPrefix
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, self.expected_tool)
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class ExtractThenCall[T: BaseModel]:
    """Extract typed output from previous call, use in next call."""

    expected_tool: str
    output_type: type[T]
    make_next: Callable[[T], tuple[MCPMountPrefix, str, BaseModel]]

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        output = assert_and_extract(req, self.expected_tool, self.output_type)
        server, tool, args = self.make_next(output)
        return factory.make_mcp_tool_call(server, tool, args)


@dataclass
class Finish:
    """Final turn: assert completion and return message."""

    expected_tool: str
    message: str = "Done"

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, self.expected_tool)
        return factory.make_assistant_message(self.message)


@dataclass
class AssistantMessage:
    """Return assistant message without checking previous tool.

    Use for simple sequences where you don't need to validate tool completion.
    For complex workflows, prefer Finish which validates the final tool.
    """

    message: str

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_assistant_message(self.message)


@dataclass
class AssertDockerExecThenFinish:
    """Assert docker exec succeeded and stdout contains expected text, then finish.

    Use to validate that a command executed successfully and produced expected output.
    Fails if:
    - Previous call was not docker_exec
    - Exit code is not 0
    - stdout doesn't contain expected_output
    """

    expected_output: str
    message: str = "Done"

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, "docker_exec")
        output = assert_and_extract(req, "docker_exec", BaseExecResult)

        # Assert exit code is 0
        if not isinstance(output.exit, Exited) or output.exit.exit_code != 0:
            stderr_text = output.stderr if isinstance(output.stderr, str) else output.stderr.truncated_text
            stdout_text = output.stdout if isinstance(output.stdout, str) else output.stdout.truncated_text
            raise AssertionError(
                f"Expected exit code 0, got {output.exit}\nstdout: {stdout_text}\nstderr: {stderr_text}"
            )

        # Assert stdout contains expected text
        stdout_text = output.stdout if isinstance(output.stdout, str) else output.stdout.truncated_text
        if self.expected_output not in stdout_text:
            raise AssertionError(f"Expected stdout to contain {self.expected_output!r}, got {stdout_text!r}")

        return factory.make_assistant_message(self.message)


@dataclass
class AssertDockerExecThenCall:
    """Assert docker exec succeeded and stdout contains expected text, then make another call.

    Use when you need to chain docker exec calls with validation between them.
    Fails if:
    - Previous call was not docker_exec
    - Exit code is not 0
    - stdout doesn't contain expected_output
    """

    expected_output: str
    next_cmd: list[str]
    timeout_ms: int = 30000
    tool_name: str = "exec"

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, "docker_exec")
        output = assert_and_extract(req, "docker_exec", BaseExecResult)

        # Assert exit code is 0
        if not isinstance(output.exit, Exited) or output.exit.exit_code != 0:
            stderr_text = output.stderr if isinstance(output.stderr, str) else output.stderr.truncated_text
            stdout_text = output.stdout if isinstance(output.stdout, str) else output.stdout.truncated_text
            raise AssertionError(
                f"Expected exit code 0, got {output.exit}\nstdout: {stdout_text}\nstderr: {stderr_text}"
            )

        # Assert stdout contains expected text
        stdout_text = output.stdout if isinstance(output.stdout, str) else output.stdout.truncated_text
        if self.expected_output not in stdout_text:
            raise AssertionError(f"Expected stdout to contain {self.expected_output!r}, got {stdout_text!r}")

        return factory.make(factory.docker_exec(self.next_cmd, timeout_ms=self.timeout_ms, tool_name=self.tool_name))


@dataclass
class DockerExecCall:
    """Make a docker exec tool call with convenient parameters.

    Uses factory.docker_exec() helper to avoid manual ExecInput construction.

    Example:
        DockerExecCall(["echo", "hello"], timeout_ms=5000)
    """

    cmd: list[str]
    timeout_ms: int = 30000
    cwd: Path | None = None
    env: list[str] | None = None
    user: str | None = None
    tool_name: str = "exec"

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make(
            factory.docker_exec(
                self.cmd,
                timeout_ms=self.timeout_ms,
                cwd=self.cwd,
                env=self.env,
                user=self.user,
                tool_name=self.tool_name,
            )
        )


@dataclass
class DockerExecCallWithBootstrapValidation(DockerExecCall):
    """Make a docker exec call after validating bootstrap succeeded.

    Use this instead of DockerExecCall when the test has bootstrap docker exec
    commands that should be validated before the first agent tool call.
    """

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_bootstrap_exec_success(req)
        return super().execute(req, factory)


@dataclass
class UiEndTurnCall:
    """End turn via UI.

    Phase 3 TODO: Accept UiServer instance and use ui_server.end_turn_tool.name
    instead of hardcoded tool name.
    """

    tool_name: str = "end_turn"  # Default for backward compat, should be from server instance

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(UI_MOUNT_PREFIX, self.tool_name, EmptyArgs())


@dataclass
class UiSendMessageCall:
    """Send message via UI.

    Phase 3 TODO: Accept UiServer instance and use ui_server.send_message_tool.name
    instead of hardcoded tool name.
    """

    content: str
    tool_name: str = "send_message"  # Default for backward compat, should be from server instance

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(UI_MOUNT_PREFIX, self.tool_name, SendMessageInput(content=self.content))


@dataclass
class EchoCall:
    """Call echo test server."""

    text: str

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(ECHO_MOUNT_PREFIX, ECHO_TOOL_NAME, EchoInput(text=self.text))


@dataclass
class ApprovalPolicyAdminSetPolicyCall:
    """Set policy via approval_policy_admin."""

    source: str

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(
            APPROVAL_ADMIN_MOUNT_PREFIX, "set_policy", SetPolicyTextArgs(source=self.source)
        )
