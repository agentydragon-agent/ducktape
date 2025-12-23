"""Tests for BootstrapHandler and InitFailedError."""

from __future__ import annotations

from mcp.types import CallToolResult, TextContent
import pytest

from adgn.agent.events import ToolCallOutput
from adgn.agent.handler import BootstrapHandler, InitFailedError
from adgn.agent.loop_control import InjectItems, NoAction
from adgn.mcp.exec.models import BaseExecResult, Exited
from adgn.openai_utils.model import FunctionCallItem


@pytest.fixture
def init_call() -> FunctionCallItem:
    """Create a mock init FunctionCallItem."""
    return FunctionCallItem(
        call_id="bootstrap:init", name="runtime_exec", arguments='{"cmd": ["./init"], "timeout_ms": 5000}'
    )


@pytest.fixture
def bootstrap_handler(init_call: FunctionCallItem) -> BootstrapHandler:
    """Create a BootstrapHandler with mock init call."""
    return BootstrapHandler(init_call)


class TestBootstrapHandlerInit:
    """Tests for BootstrapHandler initialization."""

    def test_requires_function_call_item(self) -> None:
        """BootstrapHandler requires a FunctionCallItem."""
        with pytest.raises(TypeError, match="init_call must be FunctionCallItem"):
            BootstrapHandler("not a function call")  # type: ignore[arg-type]

    def test_initial_state(self, bootstrap_handler: BootstrapHandler) -> None:
        """Handler starts in uncompleted state."""
        assert not bootstrap_handler.init_complete
        assert not bootstrap_handler.init_failed


class TestBootstrapHandlerOnBeforeSample:
    """Tests for on_before_sample behavior."""

    def test_injects_init_call_first(self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem) -> None:
        """First call to on_before_sample injects the init call."""
        decision = bootstrap_handler.on_before_sample()

        assert isinstance(decision, InjectItems)
        assert len(decision.items) == 1
        assert decision.items[0] is init_call

    def test_returns_no_action_after_success(
        self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem
    ) -> None:
        """After successful init, returns NoAction."""
        # Inject init call
        bootstrap_handler.on_before_sample()

        # Simulate successful init result
        success_result = ToolCallOutput(
            call_id=init_call.call_id,
            result=CallToolResult(content=[TextContent(type="text", text="Init complete")], isError=False),
        )
        bootstrap_handler.on_tool_result_event(success_result)

        # Next call should return NoAction
        decision = bootstrap_handler.on_before_sample()
        assert isinstance(decision, NoAction)

    def test_raises_on_init_failure(self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem) -> None:
        """After failed init, raises InitFailedError."""
        # Inject init call
        bootstrap_handler.on_before_sample()

        # Simulate failed init result
        error_result = ToolCallOutput(
            call_id=init_call.call_id,
            result=CallToolResult(content=[TextContent(type="text", text="Database connection failed")], isError=True),
        )
        bootstrap_handler.on_tool_result_event(error_result)

        # Next call should raise InitFailedError
        with pytest.raises(InitFailedError, match="Database connection failed"):
            bootstrap_handler.on_before_sample()


class TestBootstrapHandlerToolResultTracking:
    """Tests for on_tool_result_event behavior."""

    def test_ignores_unrelated_tool_results(
        self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem
    ) -> None:
        """Handler ignores tool results with different call_id."""
        other_result = ToolCallOutput(
            call_id="other:call",
            result=CallToolResult(content=[TextContent(type="text", text="Some output")], isError=True),
        )
        bootstrap_handler.on_tool_result_event(other_result)

        # Should still not be complete
        assert not bootstrap_handler.init_complete
        assert not bootstrap_handler.init_failed

    def test_tracks_success(self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem) -> None:
        """Handler correctly tracks successful init."""
        success_result = ToolCallOutput(
            call_id=init_call.call_id,
            result=CallToolResult(content=[TextContent(type="text", text="Success")], isError=False),
        )
        bootstrap_handler.on_tool_result_event(success_result)

        assert bootstrap_handler.init_complete
        assert not bootstrap_handler.init_failed

    def test_tracks_failure(self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem) -> None:
        """Handler correctly tracks failed init."""
        error_result = ToolCallOutput(
            call_id=init_call.call_id,
            result=CallToolResult(content=[TextContent(type="text", text="Error: something wrong")], isError=True),
        )
        bootstrap_handler.on_tool_result_event(error_result)

        assert bootstrap_handler.init_complete
        assert bootstrap_handler.init_failed

    def test_extracts_error_message(self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem) -> None:
        """Handler extracts error message from TextContent."""
        error_result = ToolCallOutput(
            call_id=init_call.call_id,
            result=CallToolResult(content=[TextContent(type="text", text="Detailed error message here")], isError=True),
        )
        bootstrap_handler.on_tool_result_event(error_result)

        # Error message should be captured
        with pytest.raises(InitFailedError, match="Detailed error message here"):
            bootstrap_handler.on_before_sample()

    def test_handles_empty_content(self, bootstrap_handler: BootstrapHandler, init_call: FunctionCallItem) -> None:
        """Handler handles error with no content gracefully."""
        error_result = ToolCallOutput(call_id=init_call.call_id, result=CallToolResult(content=[], isError=True))
        bootstrap_handler.on_tool_result_event(error_result)

        with pytest.raises(InitFailedError, match="no output captured"):
            bootstrap_handler.on_before_sample()


class TestInitFailedError:
    """Tests for InitFailedError exception."""

    def test_message(self) -> None:
        """InitFailedError stores message correctly."""
        error = InitFailedError("Init failed: connection refused")
        assert str(error) == "Init failed: connection refused"

    def test_exec_result(self) -> None:
        """InitFailedError stores optional exec_result."""
        exec_result = BaseExecResult(exit=Exited(exit_code=1), stdout="output", stderr="error", duration_ms=100)
        error = InitFailedError("Init failed", exec_result=exec_result)
        assert error.exec_result is not None
        assert isinstance(error.exec_result.exit, Exited)
        assert error.exec_result.exit.exit_code == 1

    def test_exec_result_default(self) -> None:
        """InitFailedError defaults exec_result to None."""
        error = InitFailedError("Init failed")
        assert error.exec_result is None
