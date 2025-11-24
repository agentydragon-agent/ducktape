"""Simple filesystem isolation for props agents.

This provides basic cheating prevention by:
1. Copying workspace to a temporary isolated directory
2. Making reference files read-only
3. Providing a clean environment

This is suitable for environments where Docker/Podman are not available.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
from contextlib import contextmanager


class IsolatedWorkspace:
    """Manages an isolated workspace for running agent code.

    The workspace is a temporary directory that contains:
    - A copy of the task files (writable)
    - Read-only reference files (if provided)
    - Isolated /tmp

    The agent can only access files within this workspace.
    """

    def __init__(
        self,
        task_files: dict[str, str | bytes],
        *,
        readonly_files: dict[str, str | bytes] | None = None,
        work_dir_name: str = "workspace",
    ):
        """Initialize isolated workspace.

        Args:
            task_files: Files that the agent can read/write (path -> content)
            readonly_files: Files that are read-only (path -> content)
            work_dir_name: Name of the working directory
        """
        self.task_files = task_files
        self.readonly_files = readonly_files or {}
        self.work_dir_name = work_dir_name
        self.temp_dir: Path | None = None
        self.workspace_path: Path | None = None

    def __enter__(self) -> Path:
        """Set up the isolated workspace."""
        # Create temporary directory
        self.temp_dir = Path(tempfile.mkdtemp(prefix="isolated_workspace_"))

        # Create workspace directory
        self.workspace_path = self.temp_dir / self.work_dir_name
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        # Write task files (writable)
        for rel_path, content in self.task_files.items():
            file_path = self.workspace_path / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                file_path.write_bytes(content)
            else:
                file_path.write_text(content)

        # Write readonly files
        readonly_dir = self.workspace_path / ".readonly"
        if self.readonly_files:
            readonly_dir.mkdir(parents=True, exist_ok=True)
            for rel_path, content in self.readonly_files.items():
                file_path = readonly_dir / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    file_path.write_bytes(content)
                else:
                    file_path.write_text(content)
                # Make readonly
                file_path.chmod(0o444)

        return self.workspace_path

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up the isolated workspace."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run(
        self,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command in the isolated workspace.

        Args:
            cmd: Command and arguments
            cwd: Working directory (defaults to workspace root)
            env: Environment variables (merged with current env)
            timeout: Timeout in seconds
            capture_output: Whether to capture stdout/stderr

        Returns:
            CompletedProcess with result
        """
        if not self.workspace_path:
            raise RuntimeError("Workspace not set up - use as context manager")

        # Prepare environment
        run_env = os.environ.copy()
        run_env["HOME"] = str(self.temp_dir)
        run_env["TMPDIR"] = str(self.temp_dir / "tmp")
        Path(run_env["TMPDIR"]).mkdir(exist_ok=True)

        if env:
            run_env.update(env)

        # Set working directory
        work_dir = cwd or self.workspace_path

        # Run command
        return subprocess.run(
            cmd,
            cwd=work_dir,
            env=run_env,
            timeout=timeout,
            capture_output=capture_output,
            text=True,
            check=False,
        )

    def collect_files(self, pattern: str = "**/*") -> dict[str, str]:
        """Collect all files from workspace matching pattern.

        Args:
            pattern: Glob pattern for files to collect

        Returns:
            Dict of relative path -> content
        """
        if not self.workspace_path:
            raise RuntimeError("Workspace not set up")

        result = {}
        for file_path in self.workspace_path.glob(pattern):
            if file_path.is_file() and not file_path.is_relative_to(self.workspace_path / ".readonly"):
                try:
                    rel_path = file_path.relative_to(self.workspace_path)
                    result[str(rel_path)] = file_path.read_text()
                except (UnicodeDecodeError, OSError):
                    # Skip binary files or files we can't read
                    pass

        return result


@contextmanager
def isolated_workspace(
    task_files: dict[str, str | bytes],
    readonly_files: dict[str, str | bytes] | None = None,
):
    """Context manager for creating an isolated workspace.

    Usage:
        with isolated_workspace({"main.py": "print('hello')"}) as ws:
            result = ws.run(["python", "main.py"])
            print(result.stdout)
    """
    workspace = IsolatedWorkspace(task_files, readonly_files=readonly_files)
    workspace_path = workspace.__enter__()
    try:
        yield workspace
    finally:
        workspace.__exit__(None, None, None)


# High-level convenience function
def run_in_isolation(
    cmd: list[str],
    task_files: dict[str, str | bytes],
    *,
    readonly_files: dict[str, str | bytes] | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run a command in isolation and collect results.

    Args:
        cmd: Command to run
        task_files: Files the agent can modify
        readonly_files: Reference files (read-only)
        env: Environment variables
        timeout: Timeout in seconds

    Returns:
        Tuple of (CompletedProcess, output_files)
    """
    with isolated_workspace(task_files, readonly_files) as ws:
        result = ws.run(cmd, env=env, timeout=timeout)
        output_files = ws.collect_files()
        return result, output_files
