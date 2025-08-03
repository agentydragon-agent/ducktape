"""Server-only worktree authorization functions.

This module contains functions that should NEVER be imported by client code.
These operations are server-authority-only to maintain the security model.
"""

from ..shared.protocol import WorktreeID


def make_worktree_id(dirname: str) -> WorktreeID:
    """Server-only: Create a worktree ID from directory name under worktrees dir.

    This function should NEVER be called from client code. Clients should obtain
    WorktreeIDs from server responses only.
    """
    return WorktreeID(f"wtid:{dirname}")
