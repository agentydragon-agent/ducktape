"""Bazel wrapper for Claude Code — sets up environment and execs bazel.

Both modes inject --bazelrc=<per-session-bazelrc> via SESSION_BAZELRC.
In web mode, HTTPS_PROXY is already set by Anthropic with fresh JWT credentials;
the session bazelrc configures Bazel to authenticate directly with the egress proxy
using Java's Authenticator mechanism — no local auth proxy shim needed.

Routes to the correct binary based on invocation name: if invoked as "bazelisk",
execs bazelisk; if invoked as "bazel", execs bazel. The shell wrapper sets
_BAZEL_WRAPPER_NAME from basename($0).

Reads configuration from environment variables set by session_start.py.
"""

import logging
import os
import sys
from pathlib import Path

from devinfra.claude.debug import log_entrypoint_debug
from devinfra.claude.env_file import ENV_BAZELISK_PATH, ENV_SESSION_BAZELRC
from devinfra.claude.settings import HookSettings
from util.env import get_required_env

logger = logging.getLogger(__name__)

# Set by the shell wrapper script from basename($0) and dirname($0)
_WRAPPER_NAME_ENV = "_BAZEL_WRAPPER_NAME"
_WRAPPER_DIR_ENV = "_BAZEL_WRAPPER_DIR"


def _invocation_name() -> str:
    """Determine the binary name this wrapper was invoked as (bazel or bazelisk)."""
    return os.environ.get(_WRAPPER_NAME_ENV, "bazel")


def _setup_logging(settings: HookSettings) -> None:
    """Configure logging to both stderr and file.

    File logging persists even if the subprocess is killed (e.g., by test timeout),
    making it available for artifact collection.
    """
    formatter = logging.Formatter("[bazel-wrapper] %(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    # Stderr: only warnings and errors (keep output quiet on happy path)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    # File: verbose (DEBUG+) for post-mortem debugging
    log_file = settings.get_sandbox_writable_dir() / "bazel-wrapper.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(stderr_handler)
    root_logger.addHandler(file_handler)

    # Show log file path on stderr so users know where to look
    print(f"[bazel-wrapper] log: {log_file}", file=sys.stderr)
    logger.info("bazel_wrapper started")


def _resolve_real_binary() -> str:
    """Resolve the real bazel/bazelisk binary path.

    Web mode: reads BAZELISK_PATH (set by session hook to the downloaded bazelisk).
    CLI mode: finds the binary matching the invocation name (bazel or bazelisk)
    on PATH, skipping our own wrapper directory.
    """
    env_path = os.environ.get(ENV_BAZELISK_PATH)
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(f"{ENV_BAZELISK_PATH}={env_path} does not exist")
        return env_path

    # CLI mode: find the real binary matching our invocation name
    invoked_as = _invocation_name()
    wrapper_dir = os.environ.get(_WRAPPER_DIR_ENV, "")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if wrapper_dir and Path(directory).resolve() == Path(wrapper_dir).resolve():
            continue
        candidate = Path(directory) / invoked_as
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise FileNotFoundError(f"No {invoked_as} found on PATH")


def main() -> None:
    """Main entry point."""
    settings = HookSettings()

    _setup_logging(settings)
    log_entrypoint_debug("bazel_wrapper")

    bazelrc_path = get_required_env(ENV_SESSION_BAZELRC)
    real_binary = _resolve_real_binary()

    logger.info("Execing %s (invoked as %s)", real_binary, _invocation_name())
    os.execvp(real_binary, [real_binary, f"--bazelrc={bazelrc_path}", *sys.argv[1:]])


if __name__ == "__main__":
    main()
