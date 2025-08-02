"""Shared test utilities to avoid duplication across test files."""

import subprocess


def run_cli_command(args, cwd=None, env=None, timeout: float = 60.0):
    """Run the actual CLI command as subprocess."""
    cmd = ["python3", "-m", "wt.cli"] + args
    if env is None:
        env = os.environ.copy()
    # Ensure local package importable when not installed
    try:
        from pathlib import Path
        project_root = str(Path(__file__).resolve().parents[1])
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{project_root}:{existing}" if existing else project_root
    except Exception:
        pass
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env, timeout=timeout, check=False)


def run_cli_sh_command(args, env, timeout: float = 60.0):
    """Run the CLI command with 'sh' subcommand as subprocess."""
    cmd = ["python3", "-m", "wt.cli", "sh"] + args
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, check=False)
