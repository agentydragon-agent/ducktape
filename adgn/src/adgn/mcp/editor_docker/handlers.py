from __future__ import annotations

from agent_core.events import ToolCallOutput
from agent_core.handler import BaseHandler
from agent_core.loop_control import Abort
from mcp_infra.calltool import extract_structured_content
from mcp_infra.exec.models import BaseExecResult


class TerminateOnEditorSubmit(BaseHandler):
    """Abort after the submit helper finishes inside the container.

    We count docker_exec results: bootstrap issues two execs, the helper submit
    call is the third. Abort after the third exec result to prevent further
    sampling once the helper has called the MCP-over-HTTP submit tool.
    """

    def __init__(self) -> None:
        self._exec_count = 0
        self._submitted = False

    def on_tool_result_event(self, evt: ToolCallOutput):
        try:
            extract_structured_content(evt.result, BaseExecResult)
        except (KeyError, TypeError, ValueError):  # Not an exec result or malformed
            return

        self._exec_count += 1
        if self._exec_count >= 3:
            self._submitted = True
        return

    def on_before_sample(self):
        if self._submitted:
            return Abort()
        return super().on_before_sample()
