from __future__ import annotations

from typing import Any, Dict

from .local_server import LocalServer, ToolDef
from .local_tools import EXEC_PARAMETERS_SCHEMA, exec_handler

class LocalExecServer(LocalServer):
    """Stateful local exec server (can add state later if needed)."""

    def __init__(self, name: str = "local"):
        super().__init__(name)
        self.invocations = 0  # example state

    def get_tools(self) -> Dict[str, ToolDef]:
        def handler(args: dict[str, Any]) -> dict[str, Any]:
            self.invocations += 1
            return exec_handler(args)

        return {
            "exec": (
                "Execute a shell command and return exit, stdout, stderr.",
                EXEC_PARAMETERS_SCHEMA,
                handler,
            )
        }
