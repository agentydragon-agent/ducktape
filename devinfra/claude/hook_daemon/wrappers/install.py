"""Wrapper installation — installs PATH-intercepting shell wrappers during session start."""

import logging
from pathlib import Path

from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import ENV_SESSION_DIR
from util.bazel.subprocess import write_shell_wrapper

logger = logging.getLogger(__name__)

# Env var baked into every wrapper so the wrapper can skip its own directory when
# resolving the real binary on PATH.
WRAPPER_DIR_ENV = "_DUCKTAPE_WRAPPER_DIR"


def install(binary_name: str, module: str, paths: SessionPaths) -> Path:
    """Install a shell wrapper script at paths.wrapper_dir/<binary_name>."""
    wrapper_dir = paths.wrapper_dir
    wrapper_path = wrapper_dir / binary_name

    wrapper_dir.mkdir(parents=True, exist_ok=True)

    baked_env: dict[str, str | Path] = {ENV_SESSION_DIR: str(paths.session_dir)}
    extra_lines = f'export {WRAPPER_DIR_ENV}="$(cd "$(dirname "$0")" && pwd)"'
    write_shell_wrapper(wrapper_path, module, baked_env=baked_env, extra_lines=extra_lines)
    logger.info("Installed %s wrapper at %s", binary_name, wrapper_path)

    return wrapper_path
