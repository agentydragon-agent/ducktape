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
    stderr: str


def run_env_script(script_path: Path, *, timeout: int = 30) -> EnvScriptResult:
    """Run a shell env script, return the new/changed env vars.

    Does NOT mutate os.environ — caller decides what to do with the result.
    """
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(script_path))} && env -0"],
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    stderr = result.stderr.decode(errors="replace").strip()

    if result.returncode != 0:
        logger.error("%s exited %d: %s", script_path, result.returncode, stderr)
        return EnvScriptResult(env_vars={}, stderr=stderr)

    # Parse NUL-delimited env vars, keep only new/changed ones
    new_env = dict(line.split("=", 1) for line in result.stdout.decode(errors="replace").split("\0") if "=" in line)
    changed = {k: v for k, v in new_env.items() if os.environ.get(k) != v}

    if changed:
        logger.info("Env script %s produced: %s", script_path.name, ", ".join(sorted(changed)))
    if stderr:
        logger.warning("Env script %s stderr:\n%s", script_path.name, stderr)

    return EnvScriptResult(env_vars=changed, stderr=stderr)
