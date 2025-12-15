"""Snapshot mount path constants and helpers.

Defines canonical paths for snapshot source code in Docker containers.
Used consistently across critics, graders, and prompt optimization agents.
"""

from __future__ import annotations

from pathlib import Path

from adgn.props.ids import SnapshotSlug

# Base directory for all snapshot mounts in containers
SNAPSHOTS_BASE_DIR = Path("/snapshots")


def snapshot_container_path(slug: SnapshotSlug) -> Path:
    """Get the container path for a snapshot's source code.

    Pattern: /snapshots/<slug>

    Agents should NOT know which split (train/valid/test) a snapshot belongs to.
    The split is internal to the training system and should not leak into agent prompts.

    Args:
        slug: Snapshot slug (e.g., "ducktape/2025-11-26-00")

    Returns:
        Container path (e.g., Path("/snapshots/ducktape/2025-11-26-00"))
    """
    return SNAPSHOTS_BASE_DIR / slug
