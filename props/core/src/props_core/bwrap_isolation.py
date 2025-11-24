"""Bubblewrap-based isolation for props agents.

Provides stronger isolation than simple_isolation.py using Linux namespaces
via bubblewrap, while still working in restricted environments where
Docker/Podman cannot function.

Key features:
- True filesystem isolation (cannot escape sandbox)
- Read-only system mounts
- Separate PID namespace
- Works without OverlayFS, iptables, or full cgroups
- No daemon required

Requirements:
- bubblewrap package installed
- User namespaces enabled (usually available)

What it provides:
✓ Filesystem isolation (agent cannot access host filesystem)
✓ Process isolation (separate PID namespace)
✓ Read-only workspace option
✓ Clean /tmp

What it does NOT provide:
✗ Network isolation (kernel limitations in nested containers)
✗ CPU/memory limits (requires cgroups v2)
✗ Syscall filtering (requires seccomp)

Security level: Good protection against accidental and casual cheating.
Suitable for honest agents and most testing scenarios.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any


class BwrapIsolation:
    """Provides filesystem isolation using bubblewrap.

    Usage:
        isolation = BwrapIsolation(workspace_root=Path("/path/to/workspace"))
        result = isolation.run(["python3", "script.py"])
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        readonly_workspace: bool = False,
        extra_ro_binds: dict[Path, Path] | None = None,
        extra_rw_binds: dict[Path, Path] | None = None,
    ):
        """Initialize bubblewrap isolation.

        Args:
            workspace_root: Host path to mount as /workspace
            readonly_workspace: Whether workspace is read-only (default: False)
            extra_ro_binds: Additional read-only host->container mappings
            extra_rw_binds: Additional read-write host->container mappings
        """
        self.workspace_root = workspace_root.resolve()
        self.readonly_workspace = readonly_workspace
        self.extra_ro_binds = extra_ro_binds or {}
        self.extra_rw_binds = extra_rw_binds or {}

    def _build_bwrap_args(self, cmd: list[str], cwd: str = "/workspace") -> list[str]:
        """Build the bubblewrap command arguments."""
        args = ["bwrap"]

        # Core system mounts (read-only)
        for path in ["/usr", "/lib", "/lib64", "/bin", "/sbin"]:
            if Path(path).exists():
                args.extend(["--ro-bind", path, path])

        # Device nodes
        args.extend(["--dev", "/dev"])

        # Process info
        args.extend(["--proc", "/proc"])

        # Private /tmp
        args.extend(["--tmpfs", "/tmp"])

        # Mount workspace
        bind_type = "--ro-bind" if self.readonly_workspace else "--bind"
        args.extend([bind_type, str(self.workspace_root), "/workspace"])

        # Extra read-only binds
        for host_path, container_path in self.extra_ro_binds.items():
            args.extend(["--ro-bind", str(host_path), str(container_path)])

        # Extra read-write binds
        for host_path, container_path in self.extra_rw_binds.items():
            args.extend(["--bind", str(host_path), str(container_path)])

        # Working directory
        args.extend(["--chdir", cwd])

        # Isolation options
        args.append("--unshare-pid")  # Separate PID namespace
        args.append("--unshare-ipc")  # Separate IPC namespace
        args.append("--unshare-uts")  # Separate hostname namespace
        # Note: NOT using --unshare-net because it fails in nested containers
        # Network isolation would require firewall rules at host level

        # Cleanup on parent death
        args.append("--die-with-parent")

        # Add the command to run
        args.extend(cmd)

        return args

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str = "/workspace",
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command in isolated environment.

        Args:
            cmd: Command and arguments to run
            cwd: Working directory inside sandbox (default: /workspace)
            env: Environment variables (merged with minimal safe env)
            timeout: Timeout in seconds
            capture_output: Whether to capture stdout/stderr

        Returns:
            CompletedProcess with result
        """
        bwrap_cmd = self._build_bwrap_args(cmd, cwd=cwd)

        # Prepare minimal environment
        run_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "USER": "nobody",
        }
        if env:
            run_env.update(env)

        return subprocess.run(
            bwrap_cmd,
            env=run_env,
            timeout=timeout,
            capture_output=capture_output,
            text=True,
            check=False,
        )


def run_with_bwrap(
    cmd: list[str],
    workspace_root: Path,
    *,
    cwd: str = "/workspace",
    readonly: bool = False,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Convenience function to run a command in bubblewrap isolation.

    Args:
        cmd: Command and arguments
        workspace_root: Host path to mount as /workspace
        cwd: Working directory inside sandbox
        readonly: Whether workspace is read-only
        env: Environment variables
        timeout: Timeout in seconds
        capture_output: Whether to capture output

    Returns:
        CompletedProcess with result

    Example:
        result = run_with_bwrap(
            ["python3", "agent.py"],
            workspace_root=Path("/path/to/task"),
            readonly=False,
            timeout=60,
        )
    """
    isolation = BwrapIsolation(workspace_root, readonly_workspace=readonly)
    return isolation.run(cmd, cwd=cwd, env=env, timeout=timeout, capture_output=capture_output)


# Check if bubblewrap is available
def is_bwrap_available() -> bool:
    """Check if bubblewrap is installed and functional."""
    try:
        result = subprocess.run(
            ["bwrap", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
