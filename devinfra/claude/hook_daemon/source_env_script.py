"""Run a shell env script and return the new/changed environment variables.

The script is expected to output `export KEY=VALUE` lines on stdout
(same format as devinfra/secrets/*.sh). Stderr is captured and returned
for logging/mailbox reporting.
"""

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvScriptResult:
    """Result of running an env script."""

    env_vars: dict[str, str]
    raw_exports: str
    stderr: str


def run_env_script(script_path: Path, *, timeout: int = 30) -> EnvScriptResult:
    """Run a shell env script, return the new/changed env vars and raw export lines.

    Does NOT mutate os.environ — caller decides what to do with the result.

    Returns both:
    - env_vars: parsed dict for os.environ.update() (daemon-side usage)
    - raw_exports: raw stdout from the script (export lines, pasted into session env file)
    """
    # First, capture the raw export lines (stdout of the script itself)
    raw_result = subprocess.run(
        ["bash", script_path],
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    raw_exports = raw_result.stdout.decode(errors="replace").strip()
    stderr = raw_result.stderr.decode(errors="replace").strip()

    if raw_result.returncode != 0:
        logger.error("%s exited %d: %s", script_path, raw_result.returncode, stderr)
        return EnvScriptResult(env_vars={}, raw_exports="", stderr=stderr)

    # Second, run with env -0 to get parsed key=value pairs for os.environ
    env_result = subprocess.run(
        f"source {shlex.quote(str(script_path))} && env -0",
        shell=True,
        executable="bash",
        check=False,
        capture_output=True,
        timeout=timeout,
    )

    if env_result.returncode != 0:
        logger.error("%s env parse failed: %s", script_path, env_result.stderr.decode(errors="replace").strip())
        return EnvScriptResult(env_vars={}, raw_exports=raw_exports, stderr=stderr)

    new_env = dict(line.split("=", 1) for line in env_result.stdout.decode(errors="replace").split("\0") if "=" in line)
    changed = {k: v for k, v in new_env.items() if os.environ.get(k) != v}

    if changed:
        logger.info("Env script %s produced: %s", script_path.name, ", ".join(sorted(changed)))
    if stderr:
        logger.warning("Env script %s stderr:\n%s", script_path.name, stderr)

    return EnvScriptResult(env_vars=changed, raw_exports=raw_exports, stderr=stderr)
