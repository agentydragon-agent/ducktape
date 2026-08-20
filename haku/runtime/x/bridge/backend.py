"""Which agent CLI the sandbox runs, and how one process of it is assembled.

Almost nothing below the envelope is Claude-specific: the console sends argv, a working directory
and an environment, and the runner pumps the process's newline-delimited JSON across console rolls.
What is CLI-specific sits at opposite ends of the wire — which flags mean "stream JSON and take
prompts on stdin" (`options.build_claude_launch`, console side), and which binary in the sandbox
image answers to them (`options.ClaudeBackend`, runner side).

A backend names those once, so a second CLI is a second implementation rather than a branch inside
the runner; what one would have to provide is <docs/second_backend.md>.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from haku.runtime.x.bridge.protocol import HarnessLaunch

# The credential the runner dials the console with. A property of the bridge rather than of any
# CLI, which is why stripping it is here and not in a backend: it is ours whichever child runs.
BRIDGE_CREDENTIAL_VARIABLE = "HAKU_AGENT_SDK_RUNNER_TOKEN"


@dataclass(frozen=True, slots=True)
class ProcessLaunch:
    """One CLI process, fully decided: which binary, which argv, where, and in what environment.

    The console's `HarnessLaunch` carries every part of this except the binary, because the
    binary is the one part the console cannot know — it is a path inside a sandbox image whose
    tag the SandboxTemplate chose. Resolving the two into this is the backend's whole job.
    """

    executable: Path
    arguments: tuple[str, ...]
    cwd: str
    environment: Mapping[str, str]

    @property
    def command(self) -> list[str]:
        return [str(self.executable), *self.arguments]


def child_environment(launch: HarnessLaunch) -> dict[str, str]:
    """This process's environment with the launch overlaid and the bridge credential removed."""
    return {
        key: value for key, value in {**os.environ, **launch.environment}.items() if key != BRIDGE_CREDENTIAL_VARIABLE
    }


class CliBackend(Protocol):
    """One agent CLI this bridge knows how to run."""

    @property
    def name(self) -> str:
        """How this CLI is named to an operator: `--harness`, and the exit-status error."""

    def resolve(self, launch: HarnessLaunch) -> ProcessLaunch:
        """The process to start for *launch*."""
        ...
