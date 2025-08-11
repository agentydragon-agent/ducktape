"""Server-only worktree authorization functions.

This module contains functions that should NEVER be imported by client code.
These operations are server-authority-only to maintain the security model.
"""

from pathlib import Path

from ..shared.configuration import Configuration
from ..shared.protocol import WorktreeID, parse_worktree_id


def make_worktree_id(dirname: str) -> WorktreeID:
    """Server-only: Create a worktree ID from directory name under worktrees dir.

    This function should NEVER be called from client code. Clients should obtain
    WorktreeIDs from server responses only.
    """
    return WorktreeID(f"wtid:{dirname}")


def wtid_to_path(config: Configuration, wtid: WorktreeID) -> Path:
    """Server-only: Convert WorktreeID to absolute worktree path using configured worktrees_dir.

    Uses config.worktrees_dir_resolved, not assumptions about WT_DIR layout.
    """
    name = parse_worktree_id(wtid)
    return (config.worktrees_dir_resolved / name).resolve()
