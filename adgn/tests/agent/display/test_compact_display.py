"""Snapshot tests for CompactDisplayHandler."""

from __future__ import annotations

from io import StringIO
import json
from typing import cast

from mcp.types import CallToolResult
from pydantic import BaseModel
import pytest
from rich.console import Console
from syrupy.assertion import SnapshotAssertion

from adgn.agent.display.rich_display import CompactDisplayHandler
from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.exec.models import BaseExecResult, ExecInput, Exited


def render_handler_to_string(call: ToolCall, output: ToolCallOutput, prefix: str = "Agent") -> str:
    """Helper to render CompactDisplayHandler events to string.

    Simulates the sequence: tool call -> tool output.
    """
    out = StringIO()
    console = Console(file=out, width=80, legacy_windows=False, color_system=None)

    # Register tool schemas so the handler can recognize ExecInput/BaseExecResult
    # Use tuple keys (MCPMountPrefix, tool_name) as expected by CompactDisplayHandler
    tool_input_schemas: dict[tuple[MCPMountPrefix, str], type[BaseModel]] = {
        (ContainerExecServer.RUNTIME_MOUNT_PREFIX, ContainerExecServer.EXEC_TOOL_NAME): cast(type[BaseModel], ExecInput)
    }
    tool_schemas: dict[tuple[MCPMountPrefix, str], type[BaseModel]] = {
        (ContainerExecServer.RUNTIME_MOUNT_PREFIX, ContainerExecServer.EXEC_TOOL_NAME): cast(
            type[BaseModel], BaseExecResult
        )
    }

    # Create handler with the console and schemas
    test_handler = CompactDisplayHandler(max_lines=20, console=console, prefix=prefix, show_usage=False)
    test_handler._tool_input_schemas = tool_input_schemas
    test_handler._tool_schemas = tool_schemas

    # Feed events in order
    test_handler.on_tool_call_event(call)
    test_handler.on_tool_result_event(output)

    return out.getvalue()


@pytest.mark.parametrize(
    "cmd",
    [
        pytest.param(["bash", "-c", "ls -la /workspace"], id="bash_-c"),
        pytest.param(["sh", "-c", "echo hello | tr a-z A-Z"], id="sh_-c"),
        pytest.param(["/bin/sh", "-lc", "sed -n '1,10p' file.txt"], id="/bin/sh_-lc"),
        pytest.param(["ruff", "check", "/workspace"], id="non_wrapped"),
        pytest.param(["python", "-c", "print('hello world')"], id="non_wrapped_spaces"),
    ],
)
def test_docker_exec_shell_unwrapping_snapshot(snapshot: SnapshotAssertion, call_id_gen, cmd: list[str]):
    """Snapshot test for docker exec command display with shell unwrapping.

    Tests the _unwrap_shell_command() logic for various shell wrappers.
    """
    # Create ExecInput
    exec_input = ExecInput(cmd=cmd, cwd="/workspace", env=None, user=None, timeout_ms=30000)

    # Create ToolCall with ExecInput
    call = ToolCall(
        name=build_mcp_function(ContainerExecServer.RUNTIME_MOUNT_PREFIX, ContainerExecServer.EXEC_TOOL_NAME),
        args_json=json.dumps(exec_input.model_dump()),
        call_id=call_id_gen(),
    )

    # Create BaseExecResult (successful exit)
    exec_result = BaseExecResult(exit=Exited(exit_code=0), stdout="output text\n", stderr="", duration_ms=125)

    # Create ToolCallOutput with BaseExecResult
    output = ToolCallOutput(
        call_id=call.call_id,
        result=CallToolResult(content=[], structuredContent=exec_result.model_dump(), isError=False),
    )

    # Render to string
    rendered = render_handler_to_string(call, output)

    # Compare against snapshot
    assert rendered == snapshot


def test_docker_exec_with_custom_cwd_snapshot(snapshot: SnapshotAssertion, call_id_gen):
    """Snapshot test for docker exec with custom working directory display."""
    # Create ExecInput with custom cwd
    exec_input = ExecInput(cmd=["bash", "-c", "pwd && ls"], cwd="/tmp/custom", env=None, user=None, timeout_ms=30000)

    # Create ToolCall
    call = ToolCall(
        name=build_mcp_function(ContainerExecServer.RUNTIME_MOUNT_PREFIX, ContainerExecServer.EXEC_TOOL_NAME),
        args_json=json.dumps(exec_input.model_dump()),
        call_id=call_id_gen(),
    )

    # Create BaseExecResult
    exec_result = BaseExecResult(
        exit=Exited(exit_code=0), stdout="/tmp/custom\nfile1.txt\nfile2.py\n", stderr="", duration_ms=89
    )

    # Create ToolCallOutput
    output = ToolCallOutput(
        call_id=call.call_id,
        result=CallToolResult(content=[], structuredContent=exec_result.model_dump(), isError=False),
    )

    # Render to string
    rendered = render_handler_to_string(call, output)

    # Compare against snapshot
    assert rendered == snapshot
