"""Harness backends linked into the shared runner binary.

The runner itself depends only on ``CliBackend`` and receives this registry at its process-entry
composition boundary. Adding another harness registers another backend here; it does not add a
provider branch to the transport loop.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from haku.runtime.x.bridge.backend import CliBackend
from haku.runtime.x.bridge.options import ClaudeBackend, claude_backend

BackendFactory = Callable[[Path | None], CliBackend]


def runner_backends() -> Mapping[str, BackendFactory]:
    return {ClaudeBackend.name: claude_backend}
