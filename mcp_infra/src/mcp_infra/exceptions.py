"""Exceptions for mcp_infra package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_infra.exec.models import BaseExecResult

__all__ = ["InitFailedError"]


class InitFailedError(Exception):
    """Raised when init script fails (non-zero exit, truncated output, or MCP error)."""

    exec_result: BaseExecResult | None

    def __init__(self, message: str, *, exec_result: BaseExecResult | None = None):
        from mcp_infra.exec.models import TruncatedStream  # noqa: PLC0415 - avoid circular import

        full_message = message
        if exec_result is not None:
            stdout = exec_result.stdout
            stderr = exec_result.stderr
            stdout_text = stdout.truncated_text if isinstance(stdout, TruncatedStream) else stdout
            stderr_text = stderr.truncated_text if isinstance(stderr, TruncatedStream) else stderr
            full_message = f"{message}\n\nSTDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}"
        super().__init__(full_message)
        self.exec_result = exec_result
