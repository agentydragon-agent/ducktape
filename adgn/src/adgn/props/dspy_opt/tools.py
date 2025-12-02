"""Workspace-aware tool wrappers for DSPy ReAct.

DSPy tools are simple functions, but our tools need context (which workspace/container
to operate on). We use contextvars to make the current workspace available to tools
without threading it through DSPy's internals.

Usage:
    async with workspace_context(hydrated_specimen):
        # Now tools can access the workspace
        result = await critic_module(specimen_slug=..., target_files=...)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adgn.props.specimens.hydrated import HydratedSpecimen

# Context var holding the current workspace
_current_workspace: ContextVar["WorkspaceSession | None"] = ContextVar("current_workspace", default=None)


@dataclass
class WorkspaceSession:
    """Active workspace session with container access."""

    specimen: "HydratedSpecimen"
    container_exec: Any  # The docker exec callable
    content_root: Path

    def read_file(self, path: str) -> str:
        """Read file from workspace."""
        full_path = self.content_root / path
        if not full_path.exists():
            return f"[ERROR: File not found: {path}]"
        try:
            return full_path.read_text()
        except Exception as e:
            return f"[ERROR reading {path}: {e}]"

    def run_command(self, cmd: str) -> str:
        """Run command in container."""
        if self.container_exec is None:
            # Fallback to local execution (for testing)
            import subprocess

            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=self.content_root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return result.stdout + result.stderr
            except Exception as e:
                return f"[ERROR: {e}]"
        # Use container exec
        return self.container_exec(cmd)

    def grep(self, pattern: str, path: str = ".") -> str:
        """Search for pattern in files."""
        return self.run_command(f"grep -rn '{pattern}' {path} || true")

    def list_files(self, path: str = ".") -> str:
        """List files in directory."""
        return self.run_command(f"find {path} -type f -name '*.py' | head -100")


def get_workspace() -> WorkspaceSession:
    """Get current workspace from context. Raises if not set."""
    ws = _current_workspace.get()
    if ws is None:
        raise RuntimeError("No workspace in context. Use workspace_context() context manager.")
    return ws


@asynccontextmanager
async def workspace_context(specimen: "HydratedSpecimen", container_exec: Any = None):
    """Context manager that sets the current workspace for tools.

    Args:
        specimen: Hydrated specimen with content_root
        container_exec: Optional container exec function (falls back to local)
    """
    session = WorkspaceSession(
        specimen=specimen,
        container_exec=container_exec,
        content_root=specimen.content_root,
    )
    token = _current_workspace.set(session)
    try:
        yield session
    finally:
        _current_workspace.reset(token)


class WorkspaceTools:
    """DSPy-compatible tool wrappers that use context for workspace access.

    These are the tools passed to dspy.ReAct. They're simple functions
    that internally call get_workspace() to access the current specimen.
    """

    @staticmethod
    def read_file(path: str) -> str:
        """Read a file from the workspace.

        Args:
            path: Relative path to file (e.g., 'src/module.py')

        Returns:
            File contents or error message
        """
        return get_workspace().read_file(path)

    @staticmethod
    def run_command(command: str) -> str:
        """Run a shell command in the workspace container.

        Args:
            command: Shell command to execute (e.g., 'ruff check src/')

        Returns:
            Command output (stdout + stderr)
        """
        return get_workspace().run_command(command)

    @staticmethod
    def grep(pattern: str, path: str = ".") -> str:
        """Search for a regex pattern in files.

        Args:
            pattern: Regex pattern to search for
            path: Directory or file to search (default: current dir)

        Returns:
            Matching lines with file:line prefix
        """
        return get_workspace().grep(pattern, path)

    @staticmethod
    def list_files(path: str = ".") -> str:
        """List Python files in directory.

        Args:
            path: Directory to list (default: current dir)

        Returns:
            Newline-separated list of file paths
        """
        return get_workspace().list_files(path)

    @classmethod
    def as_list(cls) -> list:
        """Return tools as a list for dspy.ReAct."""
        return [cls.read_file, cls.run_command, cls.grep, cls.list_files]
