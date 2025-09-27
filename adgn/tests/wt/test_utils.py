"""Shared test utilities to avoid duplication across test files."""

from datetime import timedelta
import os
import subprocess


def add_project_root_to_env(env: dict) -> None:
    """Deprecated: no-op. Rely on installed adgn package for imports."""
    return


def run_cli_command(
    args,
    cwd=None,
    env=None,
    timeout: timedelta = timedelta(seconds=60.0),
    stdin=None,
):
    """Run the actual CLI command as subprocess."""
    cmd = ["python3", "-m", "adgn.wt.cli", *args]
    if env is None:
        env = os.environ.copy()
    add_project_root_to_env(env)
    seconds = timeout.total_seconds()
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=seconds,
        check=False,
        stdin=stdin,
    )


def run_cli_sh_command(args, env, timeout: timedelta = timedelta(seconds=60.0)):
    """Run the CLI command with 'sh' subcommand as subprocess."""
    return run_cli_command(["sh", *args], env=env, timeout=timeout)
