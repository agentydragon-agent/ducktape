"""Hook daemon entry point — starts uvicorn on a Unix domain socket."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from filelock import FileLock

from devinfra.claude.hook_daemon.config import HookConfig, OtelConfig
from devinfra.claude.hook_daemon.server import create_app
from devinfra.claude.hook_daemon.source_env_script import run_env_script
from devinfra.claude.hook_daemon.tracing import init_daemon_tracing, shutdown_tracing
from devinfra.claude.settings import HookSettings, is_web_mode

logger = logging.getLogger(__name__)


def _resolve_otel_config(hook_config: HookConfig) -> OtelConfig | None:
    """Build OtelConfig from config + env vars. Bearer token comes from env (set by env script)."""
    if not hook_config.otel:
        return None

    otel_config = hook_config.otel.with_env_overrides()
    if not otel_config.endpoint:
        return None

    # Bearer token sourced from env (set by devinfra/secrets/dev_env.sh at daemon startup)
    token = os.environ.get("DUCKTAPE_OTEL_BEARER_TOKEN")
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
    otel_config: OtelConfig | None = None
    env_script_exports: str = ""
    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir_str:
        raise RuntimeError("CLAUDE_PROJECT_DIR not set — cannot load hook config")

    project_dir = Path(project_dir_str)
    hook_config = HookConfig.load_from_repo(project_dir)

    # Run the profile's env_script to populate secrets in os.environ
    # (BUILDBUDDY_API_KEY, DUCKTAPE_OTEL_BEARER_TOKEN, etc.)
    # Raw export lines are stored and written verbatim to the session env file.
    # TODO: os.environ.update() is a footgun — env script can silently overwrite
    # any daemon env var. Consider allowlisting which vars the script may set.
    settings = HookSettings()
    profile = hook_config.resolve_profile(is_web_mode(), override=settings.profile)
    if profile.env_script:
        env_script_path = project_dir / profile.env_script
        if env_script_path.is_file():
            script_result = run_env_script(env_script_path)
            os.environ.update(script_result.env_vars)
            env_script_exports = script_result.raw_exports

    otel_config = _resolve_otel_config(hook_config)

    init_daemon_tracing(daemon_dir, otel_config=otel_config)
    app = create_app(daemon_dir, hook_config=hook_config, env_script_exports=env_script_exports)
    uvicorn.run(app, uds=args.sock, log_level="info")
    shutdown_tracing()


if __name__ == "__main__":
    main()
