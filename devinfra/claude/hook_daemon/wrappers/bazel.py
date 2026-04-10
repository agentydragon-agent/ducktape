"""Bazelisk wrapper — runtime entry point, execs real bazelisk.

Mode-aware: in web mode, refreshes proxy credentials via RPC before exec.
In CLI mode, passes through directly. Both modes inject --bazelrc.
"""

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from devinfra.claude.auth_proxy.credentials import check_credential_expiry
from devinfra.claude.auth_proxy.vars import get_upstream_proxy_url
from devinfra.claude.debug import log_entrypoint_debug
from devinfra.claude.errors import AuthProxyError
from devinfra.claude.hook_daemon.client import update_proxy_creds
from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import ENV_SESSION_DIR, is_web_mode

logger = logging.getLogger(__name__)

# Set by the shell wrapper script from dirname($0)
_WRAPPER_DIR_ENV = "_BAZEL_WRAPPER_DIR"


def warn_if_credentials_expiring() -> None:
    """Check JWT expiry from current HTTPS_PROXY env var and log warning if concerning."""
    upstream_url = get_upstream_proxy_url()
    if not upstream_url:
        return

    status = check_credential_expiry(upstream_url)

    if status.expiry is None:
        return

    minutes_remaining = (status.expiry - datetime.now(UTC)).total_seconds() / 60

    if minutes_remaining <= 0:
        logger.warning(
            "JWT EXPIRED (%.0f min ago). Start a new Claude Code session for fresh credentials", -minutes_remaining
        )
    elif minutes_remaining < 30:
        logger.info("JWT valid for %.0f min", minutes_remaining)


def _setup_logging(paths: SessionPaths) -> None:
    """Configure logging to both stderr and file."""
    formatter = logging.Formatter("[bazelisk-wrapper] %(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    log_file = paths.sandbox_writable_dir / "bazelisk-wrapper.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(stderr_handler)
    root_logger.addHandler(file_handler)

    print(f"[bazelisk-wrapper] log: {log_file}", file=sys.stderr)
    logger.info("bazelisk_wrapper started")


def _resolve_real_binary() -> str:
    """Find the real bazelisk on PATH, skipping our own wrapper directory."""
    wrapper_dir = os.environ.get(_WRAPPER_DIR_ENV, "")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if wrapper_dir and Path(directory).resolve() == Path(wrapper_dir).resolve():
            continue
        candidate = Path(directory) / "bazelisk"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise FileNotFoundError("No bazelisk found on PATH")


def _refresh_proxy_creds(paths: SessionPaths) -> None:
    """Send fresh JWT credentials to the hook daemon's in-process auth proxy via RPC."""
    https_proxy = get_upstream_proxy_url()
    if not https_proxy:
        raise AuthProxyError("No HTTPS_PROXY environment variable set")
    try:
        update_proxy_creds(https_proxy, paths)
    except OSError as e:
        raise AuthProxyError(
            f"Auth proxy RPC failed: {e}. The hook daemon may not be running. "
            f"See AGENTS.md 'Recovering from a Broken Session Start Hook' for recovery steps."
        ) from e


def _run(paths: SessionPaths) -> None:
    if is_web_mode():
        _refresh_proxy_creds(paths)
        warn_if_credentials_expiring()

    real_binary = _resolve_real_binary()

    logger.info("Execing %s", real_binary)
    os.execvp(real_binary, [real_binary, f"--bazelrc={paths.bazelrc}", *sys.argv[1:]])


def main() -> None:
    """Main entry point."""
    session_dir_str = os.environ.get(ENV_SESSION_DIR)
    if not session_dir_str:
        raise RuntimeError(f"{ENV_SESSION_DIR} environment variable is required")
    session_id = Path(session_dir_str).name
    paths = SessionPaths.from_env(session_id, dict(os.environ))

    _setup_logging(paths)
    log_entrypoint_debug("bazelisk_wrapper")

    try:
        _run(paths)
    except AuthProxyError as e:
        logger.exception(
            "Auth proxy error. The hook daemon may need restarting — start a new session or re-trigger hooks"
        )
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
