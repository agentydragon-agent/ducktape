"""Install git safety wrapper that blocks dangerous git operations."""

import logging
from pathlib import Path

from devinfra.claude.session_paths import SessionPaths
from util.bazel.subprocess import write_shell_wrapper

logger = logging.getLogger(__name__)

_WRAPPER_RUNTIME_LINES = 'export _GIT_WRAPPER_DIR="$(cd "$(dirname "$0")" && pwd)"'


def install_wrapper(paths: SessionPaths, *, wrapper_dir: Path | None = None) -> Path:
    """Install git wrapper script at <wrapper_dir>/git."""
    if wrapper_dir is None:
        wrapper_dir = paths.wrapper_dir
    wrapper_path = wrapper_dir / "git"

    wrapper_dir.mkdir(parents=True, exist_ok=True)

    write_shell_wrapper(
        wrapper_path,
        "devinfra.claude.git_wrapper",
        extra_lines=_WRAPPER_RUNTIME_LINES,
    )
    logger.info("Installed git wrapper at %s", wrapper_path)

    return wrapper_path
