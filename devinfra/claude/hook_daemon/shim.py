"""Generic PATH-intercepting shim — reports to daemon, resolves binary, execs.

All shim-specific logic (git blocking, bazelisk --bazelrc injection) lives
server-side. This is the shared runtime entrypoint for all PATH shims.

The shim name and session ID are read from env vars baked into the shell
wrapper at install time by shim_install.install().
"""

import logging
import os
import sys
from pathlib import Path

from devinfra.claude.debug import log_entrypoint_debug
from devinfra.claude.hook_daemon.client import send_shim_exec
from devinfra.claude.hook_daemon.models import ShimBlocked, ShimExecRequest
from devinfra.claude.hook_daemon.shim_install import SHIM_NAME_ENV, SHIM_SESSION_ID_ENV, resolve_real_binary
from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import ENV_SESSION_DIR

logger = logging.getLogger(__name__)


def _setup_logging(shim: str, paths: SessionPaths) -> None:
    """Configure logging to stderr and file."""
    formatter = logging.Formatter(f"[{shim}-shim] %(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(stderr_handler)

    log_file = paths.sandbox_writable_dir / f"{shim}-shim.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    print(f"[{shim}-shim] log: {log_file}", file=sys.stderr)

    logger.info("%s shim started", shim)


def _report_shim(shim: str, session_id: str, paths: SessionPaths) -> list[str]:
    """Report to daemon, handle blocks, return argv to exec with.

    On block: prints message to stderr and exits 1.
    On daemon unreachable: logs error, returns original sys.argv (fallback).
    """
    report = ShimExecRequest(shim=shim, session_id=session_id, cwd=str(Path.cwd()), argv=sys.argv, env=dict(os.environ))
    response = send_shim_exec(report, paths)
    if response is None:
        return sys.argv  # Fallback: daemon unreachable
    if isinstance(response, ShimBlocked):
        print(f"[{shim}-shim] BLOCKED: {response.message}", file=sys.stderr)
        raise SystemExit(1)
    return response.argv


def main() -> None:
    shim_name = os.environ.get(SHIM_NAME_ENV)
    session_id = os.environ.get(SHIM_SESSION_ID_ENV)
    session_dir_str = os.environ.get(ENV_SESSION_DIR)
    if not shim_name or not session_id or not session_dir_str:
        raise RuntimeError(
            f"Shim env vars not set ({SHIM_NAME_ENV}, {SHIM_SESSION_ID_ENV}, {ENV_SESSION_DIR}) "
            f"— shim must be installed via shim_install.install()"
        )

    paths = SessionPaths.from_env(session_id, dict(os.environ))
    _setup_logging(shim_name, paths)
    log_entrypoint_debug(f"{shim_name}_shim")

    argv = _report_shim(shim_name, session_id, paths)

    real = resolve_real_binary(shim_name)
    logger.info("Execing %s", real)
    os.execvp(real, [real, *argv[1:]])


if __name__ == "__main__":
    main()
