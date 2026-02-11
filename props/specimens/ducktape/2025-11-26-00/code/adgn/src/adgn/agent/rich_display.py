"""Rich-based display handler that renders events immediately."""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING, Any

from mcp import types as mcp_types
from pydantic import TypeAdapter
from rich import box
from rich.console import Console, ConsoleOptions, RenderableType
from rich.json import JSON
from rich.panel import Panel
from rich.segment import Segment
from rich.text import Text

from adgn.mcp._shared.calltool import to_pydantic
from adgn.mcp.exec.models import BaseExecResult, ExecInput, TruncatedStream
from adgn.openai_utils.model import ReasoningItem

from .handler import AssistantText, Response, ToolCall, ToolCallOutput, UserText
from .loop_control import NoLoopDecision
from .reducer import BaseHandler
from .tool_schemas import extract_tool_input_schemas, extract_tool_schemas

if TYPE_CHECKING:
    from fastmcp.server import FastMCP

# Event types that can be rendered
TurnEventType = UserText | AssistantText | ToolCall | ToolCallOutput | ReasoningItem


class MaxHeight:
    """Wrapper that constrains any renderable to max height without padding.

    Renders the inner content and truncates to max_height lines if needed.
    Short content stays compact (no padding to fill max_height).
    """

    def __init__(self, renderable: RenderableType, max_height: int):
        self.renderable = renderable
        self.max_height = max_height

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ):
        """Render content with height constraint."""
        # Render inner content to segments
        segments = list(console.render(self.renderable, options))

        # Split segments into lines (segments ending with \n are line breaks)
        lines: list[list[Segment]] = []
        current_line: list[Segment] = []

        for segment in segments:
            if '\n' in segment.text:
                # Split segment on newlines
                parts = segment.text.split('\n')
                for i, part in enumerate(parts):
                    if part:  # Non-empty part
                        current_line.append(Segment(part, segment.style))
                    if i < len(parts) - 1:  # Not the last part
                        current_line.append(Segment('\n', segment.style))
                        lines.append(current_line)
                        current_line = []
            else:
                current_line.append(segment)

        # Don't forget the last line if it doesn't end with newline
        if current_line:
            lines.append(current_line)

        # Yield lines up to max_height
        if len(lines) <= self.max_height:
            # Short content: yield all segments as-is
            yield from segments
        else:
            # Tall content: yield first max_height lines, then truncation marker
            for line in lines[:self.max_height]:
                yield from line
            yield Segment(f"... ({len(lines) - self.max_height} more lines)\n")


class RichDisplayHandler(BaseHandler):
    """Rich-based display handler that renders events immediately.

    Renders each event as it arrives with Rich formatting.
    Each event is limited to max_lines (controls both Panel height and content truncation).

    Automatically extracts tool result schemas from FastMCP servers.
    """

    def __init__(
        self,
        *,
        max_lines: int = 50,
        console: Console | None = None,
        prefix: str = "",
        servers: dict[str, FastMCP] | None = None,
    ) -> None:
        """Initialize Rich display handler.

        Args:
            max_lines: Maximum lines per event (both Panel height and content truncation)
            console: Rich console (or create default)
            prefix: Prefix for all output (default: empty string)
            servers: FastMCP server instances to extract tool schemas from (auto-extracts input/output types)
        """
        self._max_lines = max_lines
        self._console = console or Console()
        self._prefix = prefix

        # Auto-extract schemas from servers (both input and output)
        if servers:
            self._tool_input_schemas = extract_tool_input_schemas(servers)
            self._tool_schemas = extract_tool_schemas(servers)
        else:
            self._tool_input_schemas = {}
            self._tool_schemas = {}

        self._calls: dict[str, ToolCall] = {}

    # Observer hooks ---------------------------------------------------------

    def on_user_text_event(self, evt: UserText) -> None:
        self._render_event(evt)

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        self._render_event(evt)

    def on_tool_call_event(self, evt: ToolCall) -> None:
        self._calls[evt.call_id] = evt
        self._render_event(evt)

    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        self._render_event(evt)

    def on_reasoning(self, item: ReasoningItem) -> None:
        self._render_event(item)

    def on_response(self, evt: Response) -> None:
        pass  # No buffering, events already rendered

    def on_before_sample(self) -> NoLoopDecision:
        return NoLoopDecision()

    # Rendering --------------------------------------------------------------

    def _render_event(self, event: TurnEventType) -> None:
        """Render a single event immediately."""
        renderable = self._create_renderable(event)
        self._console.print(renderable)

    def _panel(
        self,
        content: RenderableType,
        title: str,
        color: str,
        *,
        bold: bool = False,
        border: bool = False,
    ) -> Panel:
        """Create a Panel with colored title and height-constrained content.

        Uses MaxHeight wrapper to truncate tall content while keeping short content compact.
        Uses horizontal-only box (no left/right borders).
        Prepends prefix to title.
        """
        style = f"bold {color}" if bold else color
        # Incorporate prefix into title as a Text object (no markup interpretation)
        full_title = f"{self._prefix}{title}" if self._prefix else title
        formatted_title = Text(full_title, style=style)

        # Wrap content with MaxHeight to enforce limit without padding
        constrained_content = MaxHeight(content, self._max_lines)

        kwargs = {"title": formatted_title, "box": box.HORIZONTALS}
        if border:
            kwargs["border_style"] = color
        return Panel(constrained_content, **kwargs)

    def _parse_tool_key(self, tool_name: str) -> tuple[str, str] | None:
        """Parse tool name into (server, tool) tuple, or None if invalid format."""
        parts = tool_name.split("_", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else None

    def _format_exec_input(self, input_data: ExecInput) -> Text:
        """Format ExecInput as readable text."""
        lines = []

        # Timeout in seconds
        timeout_sec = input_data.timeout_ms / 1000
        lines.append(f"Timeout: {timeout_sec:.1f}s")

        # Command line - special case for bash -lc
        cmd = input_data.cmd
        if len(cmd) == 3 and cmd[0] == "bash" and cmd[1] == "-lc":
            # Just show the actual command string
            lines.append(cmd[2])
        else:
            # Shell-quote the command parts
            quoted = " ".join(shlex.quote(part) for part in cmd)
            lines.append(quoted)

        return Text("\n".join(lines))

    def _format_exec_result(self, result: BaseExecResult) -> Text:
        """Format BaseExecResult as readable text."""
        lines = []

        # Exit status and duration on same line
        exit_status = result.exit
        if exit_status.kind == "exited":
            lines.append(f"Exit: {exit_status.exit_code} | Duration: {result.duration_ms}ms")
        elif exit_status.kind == "killed":
            lines.append(f"Killed: signal {exit_status.signal} | Duration: {result.duration_ms}ms")
        elif exit_status.kind == "timed_out":
            lines.append(f"Exit: timed out | Duration: {result.duration_ms}ms")

        # Stdout
        if isinstance(result.stdout, TruncatedStream):
            stdout_text = result.stdout.truncated_text + "\n[truncated]"
        else:
            stdout_text = result.stdout

        if stdout_text:
            lines.append(f"\nStdout:\n{stdout_text}")

        # Stderr
        if isinstance(result.stderr, TruncatedStream):
            stderr_text = result.stderr.truncated_text + "\n[truncated]"
        else:
            stderr_text = result.stderr

        if stderr_text:
            lines.append(f"\nStderr:\n{stderr_text}")

        return Text("\n".join(lines))

    def _create_renderable(self, event: TurnEventType) -> RenderableType:
        """Create a Rich renderable for an event by type."""
        if isinstance(event, UserText):
            return self._panel(Text(event.text), "User", "blue", bold=True, border=True)

        if isinstance(event, AssistantText):
            return self._panel(Text(event.text), "Assistant", "green", bold=True, border=True)

        if isinstance(event, ToolCall):
            # Parse args for display
            parsed = _parse_json_or_none(event.args_json)
            args = parsed if parsed is not None else {"_raw": event.args_json or "{}"}

            # Try type-based rendering if we have schema registered
            tool_key = self._parse_tool_key(event.name)
            if tool_key and tool_key in self._tool_input_schemas and parsed is not None:
                try:
                    input_type = self._tool_input_schemas[tool_key]
                    typed_input = TypeAdapter(input_type).validate_python(parsed)

                    # Special rendering for ExecInput
                    if isinstance(typed_input, ExecInput):
                        formatted = self._format_exec_input(typed_input)
                        return self._panel(formatted, f"▶ {event.name}", "cyan")
                except Exception:
                    pass  # Fall through to default JSON rendering

            return self._panel(JSON.from_data(args), f"▶ {event.name}", "cyan")

        if isinstance(event, ToolCallOutput):
            # Convert to typed result
            result = to_pydantic(event.result)
            call = self._calls.get(event.call_id)
            label = f"◀ {call.name}" if call else "◀ tool_output"

            # Try to parse structured_content using registered schema
            parsed_data: Any = result.structuredContent
            if parsed_data is not None and call:
                tool_key = self._parse_tool_key(call.name)
                if tool_key and tool_key in self._tool_schemas:
                    try:
                        result_type = self._tool_schemas[tool_key]
                        parsed_data = TypeAdapter(result_type).validate_python(
                            parsed_data
                        )
                    except Exception:
                        pass  # Keep raw structured_content

            # Determine what to display (priority: parsed_data > content > error flag)
            display_data = (
                parsed_data
                if parsed_data is not None
                else (result.content or {"isError": result.isError})
            )

            # Handle MCP content blocks
            if (
                isinstance(display_data, list)
                and display_data
                and isinstance(display_data[0], mcp_types.TextContent)
            ):
                texts = [
                    block.text
                    for block in display_data
                    if isinstance(block, mcp_types.TextContent)
                ]
                combined = "\n---\n".join(texts)
                return self._panel(Text(combined), label, "yellow")

            # Special rendering for BaseExecResult (docker_exec, runtime_exec, etc.)
            if isinstance(display_data, BaseExecResult):
                formatted = self._format_exec_result(display_data)
                return self._panel(formatted, label, "yellow")

            # Default: JSON rendering
            return self._panel(JSON.from_data(display_data), label, "yellow")

        if isinstance(event, ReasoningItem):
            return Text("💭 reasoning...", style="dim")

        # Fallback
        return Text(str(event))


def _parse_json_or_none(s: str | None) -> Any | None:
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None
