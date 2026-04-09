"""Hook daemon entry point — starts uvicorn on a Unix domain socket."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from filelock import FileLock

from devinfra.claude.hook_daemon.config import HookConfig, OtelConfig
from devinfra.claude.hook_daemon.server import app, configure
from devinfra.claude.hook_daemon.session_start.secret_sources import resolve_secret
from devinfra.claude.hook_daemon.tracing import init_daemon_tracing, shutdown_tracing
from devinfra.claude.settings import HookSettings

logger = logging.getLogger(__name__)


def _resolve_otel_config(hook_config: HookConfig, project_dir: Path) -> OtelConfig | None:
    """Build OtelConfig with bearer token resolved from SOPS. Returns None if unavailable."""
    if not hook_config.otel:
        return None

    otel_config = hook_config.otel.with_env_overrides()
    if not otel_config.endpoint:
        return None

    token_source = hook_config.secrets.otel_bearer_token
    if token_source:
        token = resolve_secret(token_source, project_dir=project_dir)
        if token:
            otel_config = OtelConfig(endpoint=otel_config.endpoint, bearer_token=token)

    return otel_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Hook daemon")
    parser.add_argument("--sock", type=str, required=True, help="UDS path to listen on")
    parser.add_argument("--daemon-dir", type=str, required=True, help="Directory for logs, env persistence")
    args = parser.parse_args()

    daemon_dir = Path(args.daemon_dir)
    daemon_dir.mkdir(parents=True, exist_ok=True)

    # Acquire exclusive flock on pidfile — held for daemon lifetime.
    # The kernel releases it on process death (flock is fd-based), so clients
    # can probe the lock to determine liveness without PID-reuse ambiguity.
    pidfile = daemon_dir / "daemon.pid"
    _pidfile_lock = FileLock(str(pidfile))
    _pidfile_lock.acquire()
    pidfile.write_text(str(os.getpid()))

    log_file = daemon_dir / "daemon.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    # Log all env var keys available at daemon startup (before any session start hook runs).
    # Values are omitted to avoid leaking secrets into logs.
    logger.info("Daemon startup env var keys: %s", sorted(os.environ))
    logger.info("Daemon startup settings: %s", HookSettings().model_dump())

    # Load config once at daemon startup. Shared by tracing init and session start handler.
    hook_config: HookConfig | None = None
    otel_config: OtelConfig | None = None
    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir_str:
        project_dir = Path(project_dir_str)
        try:
            hook_config = HookConfig.load_from_repo(project_dir)
            otel_config = _resolve_otel_config(hook_config, project_dir)
        except Exception as e:
            logger.warning("Failed to load hook config at startup: %s", e)

    init_daemon_tracing(daemon_dir, otel_config=otel_config)
    configure(daemon_dir, hook_config=hook_config)

    uvicorn.run(app, uds=args.sock, log_level="info")
    shutdown_tracing()


if __name__ == "__main__":
    main()
