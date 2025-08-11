"""Shared test utilities to avoid duplication across test files."""

import subprocess


def add_project_root_to_env(env: dict) -> None:
    """Ensure the repository root is on PYTHONPATH for tests."""
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[1])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{project_root}:{existing}" if existing else project_root


def run_cli_command(args, cwd=None, env=None, timeout: float = 60.0):
    """Run the actual CLI command as subprocess."""
    cmd = ["python3", "-m", "wt.cli", *args]
    if env is None:
        import os

        env = os.environ.copy()
    add_project_root_to_env(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=False,
    )


def run_cli_sh_command(args, env, timeout: float = 60.0):
    """Run the CLI command with 'sh' subcommand as subprocess."""
    return run_cli_command(["sh", *args], env=env, timeout=timeout)
