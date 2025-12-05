"""Rich-based display handler that renders events immediately."""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING, Any

from compact_json import Formatter  # type: ignore[import-untyped]
from mcp import types as mcp_types
from pydantic import TypeAdapter, ValidationError
from rich import box
from rich.console import Console, ConsoleOptions, RenderableType
from rich.json import JSON
from rich.panel import Panel
from rich.segment import Segment
from rich.text import Text

from adgn.mcp._shared.calltool import fastmcp_to_mcp_result
from adgn.mcp.exec.models import BaseExecResult, ExecInput, TruncatedStream
from adgn.openai_utils.model import ReasoningItem

from .handler import AssistantText, Response, ToolCall, ToolCallOutput, UserText
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

    def __rich_console__(self, console: Console, options: ConsoleOptions):
        """Render content with height constraint."""
        # Render inner content to segments
        segments = list(console.render(self.renderable, options))

        # Split segments into lines (segments ending with \n are line breaks)
        lines: list[list[Segment]] = []
        current_line: list[Segment] = []

        for segment in segments:
            if "\n" in segment.text:
                # Split segment on newlines
                parts = segment.text.split("\n")
                for i, part in enumerate(parts):
                    if part:  # Non-empty part
                        current_line.append(Segment(part, segment.style))
                    if i < len(parts) - 1:  # Not the last part
                        current_line.append(Segment("\n", segment.style))
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
            for line in lines[: self.max_height]:
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

    # Rendering --------------------------------------------------------------

    def _render_event(self, event: TurnEventType) -> None:
        """Render a single event immediately."""
        renderable = self._create_renderable(event)
        self._console.print(renderable)

    def _panel(
        self, content: RenderableType, title: str, color: str, *, bold: bool = False, border: bool = False
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

        kwargs: dict[str, object] = {"title": formatted_title, "box": box.HORIZONTALS}
        if border:
            kwargs["border_style"] = color
        return Panel(constrained_content, **kwargs)  # type: ignore[arg-type]

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
                except ValidationError:
                    pass  # Fall through to default JSON rendering

            return self._panel(JSON.from_data(args), f"▶ {event.name}", "cyan")

        if isinstance(event, ToolCallOutput):
            # Convert to typed result
            result = fastmcp_to_mcp_result(event.result)
            call = self._calls.get(event.call_id)
            label = f"◀ {call.name}" if call else "◀ tool_output"

            # Try to parse structured_content using registered schema
            parsed_data: Any = result.structuredContent
            if parsed_data is not None and call:
                tool_key = self._parse_tool_key(call.name)
                if tool_key and tool_key in self._tool_schemas:
                    try:
                        result_type = self._tool_schemas[tool_key]
                        parsed_data = TypeAdapter(result_type).validate_python(parsed_data)
                    except ValidationError:
                        pass  # Keep raw structured_content

            # Determine what to display (priority: parsed_data > content > error flag)
            display_data = parsed_data if parsed_data is not None else (result.content or {"isError": result.isError})

            # Handle MCP content blocks
            if isinstance(display_data, list) and display_data and isinstance(display_data[0], mcp_types.TextContent):
                texts = [block.text for block in display_data if isinstance(block, mcp_types.TextContent)]
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


class CompactDisplayHandler(BaseHandler):
    """Compact display handler with Claude Code-style formatting.

    Uses bullet points, indentation, and inline metadata instead of panels.
    Optimized for minimal vertical space while maintaining readability.
    """

    # Display formatting constants
    _TOOL_CALL_INDENT = 2  # Indentation for complex tool call arguments
    _TOOL_RESULT_INDENT = 2  # Indentation for tool result content
    _TOOL_RESULT_PREFIX = "  ⎿ "  # Prefix for tool result lines

    def __init__(
        self,
        *,
        max_lines: int = 50,
        console: Console | None = None,
        prefix: str = "",
        servers: dict[str, FastMCP] | None = None,
        show_usage: bool = True,
    ) -> None:
        """Initialize compact display handler.

        Args:
            max_lines: Maximum lines for truncated content
            console: Rich console (or create default)
            prefix: Prefix for tool calls/results (e.g., "critic", "optimizer")
            servers: FastMCP server instances to extract tool schemas from
            show_usage: Show token usage after each response (default: True)
        """
        self._max_lines = max_lines
        self._console = console or Console()
        self._prefix = prefix
        self._show_usage = show_usage

        # Auto-extract schemas from servers
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
        # TODO: Track cost and show it in USD (need model pricing lookup)
        if not self._show_usage or not evt.usage:
            return

        input_tok = evt.usage.input_tokens or 0
        output_tok = evt.usage.output_tokens or 0

        # Render compact usage line
        text = Text()
        text.append("  [tokens] ", style="dim yellow")
        text.append(f"{self._format_tokens(input_tok)}", style="cyan")
        text.append(" in / ", style="dim")
        text.append(f"{self._format_tokens(output_tok)}", style="green")
        text.append(" out", style="dim")

        # Model name (optional)
        if evt.usage.model:
            text.append(f"  {evt.usage.model}", style="dim italic")

        self._console.print(text)

    # Rendering --------------------------------------------------------------

    def _render_event(self, event: TurnEventType) -> None:
        """Render a single event immediately."""
        renderable = self._create_renderable(event)
        if renderable is not None:
            self._console.print(renderable)

    def _parse_tool_key(self, tool_name: str) -> tuple[str, str] | None:
        """Parse tool name into (server, tool) tuple, or None if invalid format."""
        parts = tool_name.split("_", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else None

    def _format_exec_command(self, input_data: ExecInput) -> str:
        """Format ExecInput as a shell command."""
        cmd = input_data.cmd
        # Special case for bash -lc (unwrap the actual command)
        if len(cmd) == 3 and cmd[0] == "bash" and cmd[1] == "-lc":
            return cmd[2]
        # Shell-quote the command parts
        return " ".join(shlex.quote(part) for part in cmd)

    def _format_exec_metadata(self, result: BaseExecResult) -> str:
        """Format exec result metadata (exit code, duration) for inline display."""
        parts = []

        # Exit status
        exit_status = result.exit
        if exit_status.kind == "exited":
            parts.append(f"exit_code={exit_status.exit_code}")
        elif exit_status.kind == "killed":
            parts.append(f"killed=signal_{exit_status.signal}")
        elif exit_status.kind == "timed_out":
            parts.append("exit_code=timeout")

        # Duration in seconds
        duration_sec = result.duration_ms / 1000
        parts.append(f"duration={duration_sec:.1f}s")

        return "  ".join(parts)

    def _truncate_lines(self, text: str, max_lines: int) -> str:
        """Truncate text to max_lines with indicator."""
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text
        truncated = lines[:max_lines]
        return "\n".join(truncated) + f"\n... ({len(lines) - max_lines} more lines)"

    def _indent(self, text: str, spaces: int = 2) -> str:
        """Indent each line of text."""
        indent = " " * spaces
        return "\n".join(indent + line for line in text.splitlines())

    def _format_tokens(self, count: int) -> str:
        """Format token count with k suffix for numbers >= 1000."""
        if count >= 1000:
            return f"{count / 1000:.1f}k"
        return str(count)

    def _create_renderable(self, event: TurnEventType) -> RenderableType | None:
        """Create a Rich renderable for an event by type."""
        # UserText - plain with "User:" prefix
        if isinstance(event, UserText):
            text = Text()
            text.append("User: ", style="bold blue")
            text.append(event.text)
            return text

        # AssistantText - plain with prefix if set
        if isinstance(event, AssistantText):
            text = Text()
            if self._prefix:
                text.append(f"{self._prefix}: ", style="bold green")
            else:
                text.append("Assistant: ", style="bold green")
            text.append(event.text)
            return text

        # ReasoningItem - italic summary text
        if isinstance(event, ReasoningItem):
            if not event.summary:
                return None
            text = Text()
            if self._prefix:
                text.append(f"{self._prefix}: ", style="bold green")
            # Combine summary parts
            summary_text = " ".join(s.text for s in event.summary if s.text)
            text.append(summary_text, style="italic dim")
            return text

        # ToolCall - compact format with inline metadata when possible
        if isinstance(event, ToolCall):
            parsed = _parse_json_or_none(event.args_json)
            args = parsed if parsed is not None else {}

            # Try type-based rendering if we have schema registered
            tool_key = self._parse_tool_key(event.name)
            typed_input = None
            if tool_key and tool_key in self._tool_input_schemas and parsed is not None:
                try:
                    input_type = self._tool_input_schemas[tool_key]
                    typed_input = TypeAdapter(input_type).validate_python(parsed)
                except ValidationError:
                    pass

            text = Text()
            # Bullet with prefix and tool name
            prefix_part = f"{self._prefix}: " if self._prefix else ""
            text.append(f"● {prefix_part}", style="cyan")
            text.append(event.name, style="bold cyan")

            # Special handling for exec
            if isinstance(typed_input, ExecInput):
                cmd_str = self._format_exec_command(typed_input)
                text.append(f": {cmd_str}", style="cyan")
                # Add cwd if present and not default
                if typed_input.cwd and typed_input.cwd != "/workspace":
                    text.append(f"  [cwd={typed_input.cwd}]", style="dim cyan")
            elif args:
                # Args with smart line wrapping
                formatter = Formatter(max_inline_length=self._console.width - self._TOOL_CALL_INDENT)
                json_str = formatter.serialize(args)
                # If it fits on one line and is short enough, keep it inline
                if "\n" not in json_str and len(json_str) < 80:
                    text.append(f": {json_str}", style="dim cyan")
                else:
                    # Multi-line or long - indent on next line
                    text.append("\n")
                    indented = self._indent(json_str, self._TOOL_CALL_INDENT)
                    text.append(indented, style="dim cyan")

            return text

        # ToolCallOutput - metadata inline, content indented
        if isinstance(event, ToolCallOutput):
            result = fastmcp_to_mcp_result(event.result)
            call = self._calls.get(event.call_id)

            # Try to parse structured_content using registered schema
            parsed_data: Any = result.structuredContent
            if parsed_data is not None and call:
                tool_key = self._parse_tool_key(call.name)
                if tool_key and tool_key in self._tool_schemas:
                    try:
                        result_type = self._tool_schemas[tool_key]
                        parsed_data = TypeAdapter(result_type).validate_python(parsed_data)
                    except ValidationError:
                        pass

            # Determine what to display
            display_data = parsed_data if parsed_data is not None else (result.content or {"isError": result.isError})

            text = Text()

            # Special handling for exec results
            if isinstance(display_data, BaseExecResult):
                metadata = self._format_exec_metadata(display_data)
                text.append(self._TOOL_RESULT_PREFIX, style="yellow")
                text.append(metadata, style="dim yellow")

                # Determine if we need labels for stdout/stderr
                has_stdout = bool(
                    display_data.stdout.truncated_text
                    if isinstance(display_data.stdout, TruncatedStream)
                    else display_data.stdout
                )
                has_stderr = bool(
                    display_data.stderr.truncated_text
                    if isinstance(display_data.stderr, TruncatedStream)
                    else display_data.stderr
                )
                both_present = has_stdout and has_stderr

                # Stdout
                if has_stdout:
                    stdout_text = (
                        display_data.stdout.truncated_text + "\n[truncated]"
                        if isinstance(display_data.stdout, TruncatedStream)
                        else display_data.stdout
                    )
                    truncated = self._truncate_lines(stdout_text, self._max_lines)
                    if both_present:
                        text.append("\n    stdout:\n")
                    else:
                        text.append("\n")
                    text.append(self._indent(truncated, self._TOOL_RESULT_INDENT))

                # Stderr
                if has_stderr:
                    stderr_text = (
                        display_data.stderr.truncated_text + "\n[truncated]"
                        if isinstance(display_data.stderr, TruncatedStream)
                        else display_data.stderr
                    )
                    truncated = self._truncate_lines(stderr_text, self._max_lines)
                    if both_present:
                        text.append("\n    stderr:\n", style="red")
                    else:
                        text.append("\n")
                    text.append(self._indent(truncated, self._TOOL_RESULT_INDENT), style="red")

                return text

            # Handle error results
            if result.isError:
                text.append("  ⎿ ERROR: ", style="bold red")
                # Extract error message from content blocks
                if isinstance(display_data, list):
                    error_texts = [block.text for block in display_data if isinstance(block, mcp_types.TextContent)]
                    error_msg = "\n".join(error_texts) if error_texts else str(display_data)
                else:
                    error_msg = str(display_data)
                truncated = self._truncate_lines(error_msg, self._max_lines)
                text.append(error_msg)
                return text

            # Handle text content blocks
            if isinstance(display_data, list) and display_data and isinstance(display_data[0], mcp_types.TextContent):
                texts = [block.text for block in display_data if isinstance(block, mcp_types.TextContent)]
                combined = "\n".join(texts)
                truncated = self._truncate_lines(combined, self._max_lines)
                text.append(self._TOOL_RESULT_PREFIX, style="yellow")
                if len(texts) == 1 and "\n" not in combined:
                    # Single line - keep inline
                    text.append(combined, style="yellow")
                else:
                    # Multi-line - indent
                    text.append("\n")
                    text.append(self._indent(truncated, self._TOOL_RESULT_INDENT), style="yellow")
                return text

            # Default: compact JSON with smart line wrapping
            # Calculate available width: console width minus prefix and indentation
            available_width = self._console.width - len(self._TOOL_RESULT_PREFIX) - self._TOOL_RESULT_INDENT
            formatter = Formatter(max_inline_length=available_width)
            json_str = formatter.serialize(display_data)
            truncated = self._truncate_lines(json_str, self._max_lines)
            lines = truncated.splitlines()
            if lines:
                text.append(self._TOOL_RESULT_PREFIX, style="yellow")
                text.append(lines[0] + "\n", style="dim yellow")
                if len(lines) > 1:
                    text.append(self._indent("\n".join(lines[1:]), self._TOOL_RESULT_INDENT), style="dim yellow")
            return text

        # Fallback
        return Text(str(event))
