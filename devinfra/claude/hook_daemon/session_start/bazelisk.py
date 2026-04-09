"""Install bazelisk wrapper for proxy credential injection.

The wrapper script intercepts `bazelisk` invocations to inject proxy credentials
via RPC before calling the real bazelisk binary (provided by Nix via devtools).
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import ENV_SESSION_DIR
from util.bazel.subprocess import write_shell_wrapper

logger = logging.getLogger(__name__)


@dataclass
class BazeliskSetup:
    """Result of bazelisk wrapper installation."""

    bazelisk_path: Path
    wrapper_path: Path

    @property
    def status(self) -> str:
        """Get status string for logging."""
        bazelisk_on_path = shutil.which("bazelisk")
        if bazelisk_on_path and Path(bazelisk_on_path).resolve() == self.wrapper_path.resolve():
            return f"wrapper at {self.wrapper_path}"
        if self.wrapper_path.exists():
            return f"wrapper exists but not on PATH ({self.wrapper_path})"
        return "no wrapper"


def resolve_bazelisk() -> Path:
    """Find bazelisk on PATH (provided by Nix devtools package)."""
    bazelisk = shutil.which("bazelisk")
    if bazelisk:
        return Path(bazelisk)
    raise RuntimeError("bazelisk not found on PATH (expected from Nix devtools package)")


_WRAPPER_RUNTIME_LINES = 'export _BAZEL_WRAPPER_DIR="$(cd "$(dirname "$0")" && pwd)"'


def install_wrapper(paths: SessionPaths, *, wrapper_dir: Path | None = None) -> Path:
    """Install wrapper script that sets proxy env vars before calling bazelisk."""
    if wrapper_dir is None:
        wrapper_dir = paths.wrapper_dir
    wrapper_path = wrapper_dir / "bazelisk"

    wrapper_dir.mkdir(parents=True, exist_ok=True)

    write_shell_wrapper(
        wrapper_path,
        "devinfra.claude.bazel_wrapper",
        baked_env={ENV_SESSION_DIR: str(paths.session_dir)},
        extra_lines=_WRAPPER_RUNTIME_LINES,
    )
    logger.info("Installed bazelisk wrapper at %s", wrapper_path)

    return wrapper_path
