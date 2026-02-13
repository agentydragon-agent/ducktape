"""Tests for grader supervisor reconciliation logic.

Tests the core invariant: reconcile() converges toward one grader per
snapshot when an image is available.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest_bazel

from props.core.ids import SnapshotSlug
from props.orchestration.agent_registry import ImageResolutionError, ResolvedImage
from props.orchestration.grader_supervisor import GraderSupervisor

FAKE_IMAGE = ResolvedImage(digest="sha256:abc123", oci_ref="localhost:8000/grader@sha256:abc123")
FAKE_IMAGE_V2 = ResolvedImage(digest="sha256:def456", oci_ref="localhost:8000/grader@sha256:def456")


@dataclass
class FakeHandle:
    container_name: str
    killed: bool = False

    async def kill(self) -> None:
        self.killed = True


def _make_supervisor(snapshot_slugs: list[str], *, image: ResolvedImage | None = FAKE_IMAGE) -> GraderSupervisor:
    """Build a GraderSupervisor with mocked dependencies."""

    # Mock registry
    registry = MagicMock()

    async def resolve_image(agent_type: Any, tag: str) -> ResolvedImage:
        if image is None:
            raise ImageResolutionError("no image")
        return image

    registry.resolve_image = AsyncMock(side_effect=resolve_image)

    handle_counter = 0

    async def start_snapshot_grader(*, image: ResolvedImage, snapshot_slug: SnapshotSlug, model: str) -> FakeHandle:
        nonlocal handle_counter
        handle_counter += 1
        return FakeHandle(container_name=f"grader-{handle_counter}")

    registry.start_snapshot_grader = AsyncMock(side_effect=start_snapshot_grader)

    # Mock DB session that returns snapshot slugs
    @contextmanager
    def fake_session() -> Any:
        session = MagicMock()
        rows = [MagicMock(slug=SnapshotSlug(s)) for s in snapshot_slugs]
        session.query.return_value.all.return_value = rows
        yield session

    db = MagicMock()
    db.session = fake_session

    db_config = MagicMock()
    return GraderSupervisor(registry=registry, db_config=db_config, model="gpt-5-mini", db=db)


async def test_reconcile_spawns_for_all_snapshots():
    """reconcile() spawns a grader for each snapshot."""
    gs = _make_supervisor(["snap-a", "snap-b", "snap-c"])
    await gs.reconcile()
    assert set(gs._handles.keys()) == {"snap-a", "snap-b", "snap-c"}


async def test_reconcile_noop_when_image_unavailable():
    """reconcile() does nothing when no grader image is available."""
    gs = _make_supervisor(["snap-a"], image=None)
    await gs.reconcile()
    assert gs._handles == {}


async def test_reconcile_idempotent():
    """Calling reconcile() twice doesn't create duplicate graders."""
    gs = _make_supervisor(["snap-a", "snap-b"])
    await gs.reconcile()
    handles_first = dict(gs._handles)
    await gs.reconcile()
    # Same handles, not replaced
    assert gs._handles == handles_first


async def test_reconcile_spawns_new_snapshot():
    """reconcile() spawns for a newly added snapshot without touching existing."""
    gs = _make_supervisor(["snap-a"])
    await gs.reconcile()
    handle_a = gs._handles["snap-a"]

    # Simulate new snapshot appearing in DB
    rows = [MagicMock(slug=SnapshotSlug(s)) for s in ["snap-a", "snap-b"]]
    gs._db.session = _mock_session(rows)

    await gs.reconcile()
    # snap-a kept, snap-b added
    assert gs._handles["snap-a"] is handle_a
    assert "snap-b" in gs._handles


async def test_reconcile_kills_removed_snapshot():
    """reconcile() kills grader when snapshot disappears from DB."""
    gs = _make_supervisor(["snap-a", "snap-b"])
    await gs.reconcile()
    handle_b = gs._handles["snap-b"]

    # Simulate snap-b removed from DB
    rows = [MagicMock(slug=SnapshotSlug("snap-a"))]
    gs._db.session = _mock_session(rows)

    await gs.reconcile()
    assert "snap-b" not in gs._handles
    assert handle_b.killed


async def test_reconcile_restart_kills_and_respawns():
    """reconcile(restart_existing=True) kills all and respawns."""
    gs = _make_supervisor(["snap-a", "snap-b"])
    await gs.reconcile()
    old_a = gs._handles["snap-a"]
    old_b = gs._handles["snap-b"]

    await gs.reconcile(restart_existing=True)
    assert old_a.killed
    assert old_b.killed
    # New handles created
    assert gs._handles["snap-a"] is not old_a
    assert gs._handles["snap-b"] is not old_b


async def test_reconcile_restart_also_spawns_missing():
    """restart_existing=True also spawns graders for snapshots not yet tracked."""
    gs = _make_supervisor(["snap-a"])
    await gs.reconcile()
    old_a = gs._handles["snap-a"]

    # Add snap-b to DB, trigger restart
    rows = [MagicMock(slug=SnapshotSlug(s)) for s in ["snap-a", "snap-b"]]
    gs._db.session = _mock_session(rows)

    await gs.reconcile(restart_existing=True)
    assert old_a.killed
    assert "snap-a" in gs._handles
    assert "snap-b" in gs._handles


async def test_shutdown_kills_all():
    """shutdown() kills all tracked graders."""
    gs = _make_supervisor(["snap-a", "snap-b"])
    await gs.reconcile()
    handles = list(gs._handles.values())

    await gs.shutdown()
    assert all(h.killed for h in handles)
    assert gs._handles == {}


async def test_reconcile_noop_after_shutdown():
    """reconcile() does nothing after shutdown."""
    gs = _make_supervisor(["snap-a"])
    await gs.shutdown()
    await gs.reconcile()
    assert gs._handles == {}


def _mock_session(rows: list[Any]) -> Any:
    """Create a mock session context manager returning given rows."""

    @contextmanager
    def fake_session() -> Any:
        session = MagicMock()
        session.query.return_value.all.return_value = rows
        yield session

    return fake_session


if __name__ == "__main__":
    pytest_bazel.main()
