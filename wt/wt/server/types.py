from __future__ import annotations

import time
from pathlib import Path


class DiscoveredWorktree:
    """Filesystem-discovered worktree instance (daemon-internal)."""

    def __init__(self, path: Path, name: str):
        self.path = path
        self.name = name
        self.discovered_at = time.time()
        self.last_seen = time.time()

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        return isinstance(other, DiscoveredWorktree) and self.path == other.path
