"""Declarative step classes for test agent state machines.

See docs/test_scenario_steps.md for detailed usage guide.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from adgn.mcp.exec.models import BaseExecResult, Exited
from adgn.openai_utils.model import ResponsesRequest, ResponsesResult
from tests.support.assertions import assert_and_extract, assert_last_call
from tests.support.responses import ResponsesFactory

T = TypeVar("T", bound=BaseModel)


class Step(Protocol):
    """Protocol for step objects that can be executed in sequence."""

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult: ...


@dataclass
class MakeCall:
    """Initial turn: make a tool call."""

    server: str
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class CheckThenCall:
    """Assert previous tool completed, then call next."""

    expected_tool: str
    server: str
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
    make_next: Callable[[T], tuple[str, str, BaseModel]]

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
            raise AssertionError(f"Expected exit code 0, got {output.exit}")

        # Assert stdout contains expected text
        stdout_text = output.stdout if isinstance(output.stdout, str) else output.stdout.truncated_text
        if self.expected_output not in stdout_text:
            raise AssertionError(f"Expected stdout to contain {self.expected_output!r}, got {stdout_text!r}")

        return factory.make_assistant_message(self.message)


@dataclass
class DockerExecCall:
    """Make a docker exec tool call with convenient parameters.

    Uses factory.docker_exec() helper to avoid manual ExecInput construction.

    Example:
        DockerExecCall(["echo", "hello"], timeout_ms=5000)

    Instead of:
        MakeCall("docker", "exec", make_exec_input(["echo", "hello"], timeout_ms=5000))
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
