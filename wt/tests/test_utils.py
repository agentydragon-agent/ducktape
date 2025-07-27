"""Shared test utilities to avoid duplication across test files."""

import subprocess


def run_cli_command(args, cwd=None, env=None):
    """Run the actual CLI command as subprocess."""
    cmd = ["python3", "-m", "wt.cli"] + args
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


def run_cli_sh_command(args, env):
    """Run the CLI command with 'sh' subcommand as subprocess."""
    cmd = ["python3", "-m", "wt.cli", "sh"] + args
    return subprocess.run(cmd, capture_output=True, text=True, env=env)
