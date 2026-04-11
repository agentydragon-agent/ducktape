"""Shim installation — installs PATH-intercepting shell shims during session start."""

import logging
import os
from pathlib import Path

from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import ENV_SESSION_DIR
from util.bazel.subprocess import write_shell_wrapper

logger = logging.getLogger(__name__)

# Shim-internal env vars (baked into shell wrappers at install time).
# Double-underscore prefix = private, not part of the public DUCKTAPE_CLAUDE_HOOKS_* namespace.
SHIM_DIR_ENV = "__DUCKTAPE_CLAUDE_HOOKS_SHIM_DIR"
SHIM_NAME_ENV = "__DUCKTAPE_CLAUDE_HOOKS_SHIM_NAME"
SHIM_SESSION_ID_ENV = "__DUCKTAPE_CLAUDE_HOOKS_SHIM_SESSION_ID"

SHIM_MODULE = "devinfra.claude.hook_daemon.shim"


def install(shim_name: str, paths: SessionPaths) -> Path:
    """Install a shell shim at paths.wrapper_dir/<shim_name>."""
    wrapper_dir = paths.wrapper_dir
    shim_path = wrapper_dir / shim_name

    wrapper_dir.mkdir(parents=True, exist_ok=True)

    baked_env: dict[str, str | Path] = {
        ENV_SESSION_DIR: str(paths.session_dir),
        SHIM_SESSION_ID_ENV: paths.session_id,
        SHIM_NAME_ENV: shim_name,
    }
    extra_lines = f'export {SHIM_DIR_ENV}="$(cd "$(dirname "$0")" && pwd)"'
    write_shell_wrapper(shim_path, SHIM_MODULE, baked_env=baked_env, extra_lines=extra_lines)
    logger.info("Installed %s shim at %s", shim_name, shim_path)

    return shim_path


def resolve_real_binary(binary_name: str) -> str:
    """Find the real binary on PATH, skipping the shim directory."""
    shim_dir = os.environ.get(SHIM_DIR_ENV, "")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if shim_dir and Path(directory).resolve() == Path(shim_dir).resolve():
            continue
        candidate = Path(directory) / binary_name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError(f"No {binary_name} found on PATH (outside shim directory)")
