"""Tests for Compositor lifecycle management and cleanup."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastmcp.server import FastMCP
import pytest

from adgn.mcp.compositor.mount import Mount, MountState
from adgn.mcp.compositor.server import Compositor, CompositorState


@pytest.mark.asyncio
async def test_compositor_state_transitions():
    """Test that compositor follows correct state transitions."""
    comp = Compositor("test")

    # Initial state: CREATED
    assert comp._state == CompositorState.CREATED

    # Enter context: CREATED → ACTIVE
    async with comp:
        assert comp._state == CompositorState.ACTIVE

    # Exit context: ACTIVE → CLOSED
    assert comp._state == CompositorState.CLOSED


@pytest.mark.asyncio
async def test_double_enter_raises():
    """Test that entering compositor twice raises RuntimeError."""
    async with Compositor("test") as comp:
        # Try to enter again while already active
        with pytest.raises(RuntimeError, match="already in an active context"):
            async with comp:
                pass


@pytest.mark.asyncio
async def test_reuse_closed_compositor_raises():
    """Test that reusing closed compositor raises RuntimeError."""
    comp = Compositor("test")

    async with comp:
        pass

    # Try to reuse closed compositor
    with pytest.raises(RuntimeError, match="already closed"):
        async with comp:
            pass


@pytest.mark.asyncio
async def test_mount_after_close_raises():
    """Test that mounting after close raises RuntimeError."""
    comp = Compositor("test")

    async with comp:
        pass

    # Try to mount after close
    server = FastMCP("backend")
    with pytest.raises(RuntimeError, match=r"compositor .* is closed"):
        await comp.mount_inproc("backend", server)


@pytest.mark.asyncio
async def test_cleanup_removes_non_pinned_servers(make_make_simple_mcp):
    """Test that close() removes all non-pinned servers."""
    backend1 = make_make_simple_mcp("backend1")
    backend2 = make_make_simple_mcp("backend2")
    pinned = make_make_simple_mcp("pinned")

    async with Compositor("test") as comp:
        await comp.mount_inproc("backend1", backend1)
        await comp.mount_inproc("backend2", backend2)
        await comp.mount_inproc("pinned", pinned, pinned=True)

        # Before close: all mounted
        entries = await comp.server_entries()
        assert "backend1" in entries
        assert "backend2" in entries
        assert "pinned" in entries

    # After close: only pinned remains
    entries = await comp.server_entries()
    assert "backend1" not in entries
    assert "backend2" not in entries
    assert "pinned" in entries

    # Verify pinned server is still active
    mount = comp._mounts.get("pinned")
    assert mount is not None
    assert mount.is_active


@pytest.mark.asyncio
async def test_mount_state_transitions(make_make_simple_mcp):
    """Test that mounts follow correct state transitions."""
    backend = make_make_simple_mcp("backend")

    async with Compositor("test") as comp:
        await comp.mount_inproc("backend", backend)

        mount = comp._mounts["backend"]
        # After successful mount: ACTIVE
        assert mount.state == MountState.ACTIVE
        assert mount.is_active
        assert not mount.is_failed
        assert not mount.is_closed

        # Unmount
        await comp.unmount_server("backend")

        # After unmount: CLOSED
        assert mount.state == MountState.CLOSED
        assert not mount.is_active
        assert mount.is_closed


@pytest.mark.asyncio
async def test_mount_cleanup_is_idempotent(make_make_simple_mcp):
    """Test that mount cleanup can be called multiple times safely."""
    backend = make_make_simple_mcp("backend")

    async with Compositor("test") as comp:
        await comp.mount_inproc("backend", backend)
        mount = comp._mounts["backend"]

        # First cleanup
        await mount.cleanup()
        assert mount.is_closed

        # Second cleanup (should not raise)
        await mount.cleanup()
        assert mount.is_closed

        # Third cleanup (should not raise)
        await mount.cleanup()
        assert mount.is_closed


@pytest.mark.asyncio
async def test_accessing_inactive_mount_raises(make_make_simple_mcp):
    """Test that accessing proxy/client on inactive mount raises."""
    backend = make_make_simple_mcp("backend")

    async with Compositor("test") as comp:
        await comp.mount_inproc("backend", backend)
        mount = comp._mounts["backend"]

        # Before cleanup: accessible
        proxy = mount.proxy
        client = mount.child_client
        assert proxy is not None
        assert client is not None

        # Cleanup
        await mount.cleanup()

        # After cleanup: raises
        with pytest.raises(RuntimeError, match="not active"):
            _ = mount.proxy

        with pytest.raises(RuntimeError, match="not active"):
            _ = mount.child_client


@pytest.mark.asyncio
async def test_exception_in_body_still_cleans_up(make_make_simple_mcp):
    """Test that exceptions in context body still trigger cleanup."""
    backend = make_make_simple_mcp("backend")

    comp = Compositor("test")
    try:
        async with comp:
            await comp.mount_inproc("backend", backend)

            # Before exception: mounted
            entries = await comp.server_entries()
            assert "backend" in entries

            # Raise exception
            raise ValueError("test exception")
    except ValueError:
        pass

    # After exception: cleaned up
    assert comp._state == CompositorState.CLOSED
    entries = await comp.server_entries()
    assert "backend" not in entries


@pytest.mark.asyncio
async def test_mount_failure_does_not_leak():
    """Test that failed mounts don't leak resources."""
    # Create a server that will fail to initialize

    failing_server = FastMCP("failing")

    async with Compositor("test") as comp:
        # Mock the Mount.setup_inproc to simulate failure
        async def failing_setup(self, server, handler_factory=None):
            raise RuntimeError("Simulated mount failure")

        with (
            patch.object(Mount, "setup_inproc", failing_setup),
            pytest.raises(RuntimeError, match="Simulated mount failure"),
        ):
            # Mount should fail
            await comp.mount_inproc("failing", failing_server)

        # Server should NOT be registered
        entries = await comp.server_entries()
        assert "failing" not in entries
        assert "failing" not in comp._mounts


@pytest.mark.asyncio
async def test_close_continues_on_per_server_failure(make_make_simple_mcp):
    """Test that close() continues cleanup even if one server fails."""
    backend1 = make_make_simple_mcp("backend1")
    backend2 = make_make_simple_mcp("backend2")

    async with Compositor("test") as comp:
        await comp.mount_inproc("backend1", backend1)
        await comp.mount_inproc("backend2", backend2)

        # Break one mount's cleanup
        mount1 = comp._mounts["backend1"]

        async def failing_cleanup():
            raise RuntimeError("Simulated cleanup failure")

        mount1.cleanup = failing_cleanup

        # Store initial state
        entries_before = await comp.server_entries()
        assert "backend1" in entries_before
        assert "backend2" in entries_before

    # After close: backend2 should still be cleaned up despite backend1 failure
    # (backend1 will fail cleanup but be removed from dict)
    entries_after = await comp.server_entries()
    assert "backend2" not in entries_after
    # Both should be gone from dict
    assert "backend1" not in comp._mounts
    assert "backend2" not in comp._mounts


@pytest.mark.asyncio
async def test_concurrent_mount_operations_safe(make_make_simple_mcp):
    """Test that concurrent mount operations don't corrupt state."""

    async def mount_many(comp, prefix, count):
        """Mount multiple servers concurrently."""
        tasks = []
        for i in range(count):
            name = f"{prefix}_{i}"
            server = make_make_simple_mcp(name)
            tasks.append(comp.mount_inproc(name, server))
        await asyncio.gather(*tasks)

    async with Compositor("test") as comp:
        # Mount many servers concurrently
        await asyncio.gather(mount_many(comp, "group_a", 5), mount_many(comp, "group_b", 5))

        # All should be mounted
        entries = await comp.server_entries()
        for i in range(5):
            assert f"group_a_{i}" in entries
            assert f"group_b_{i}" in entries


@pytest.mark.asyncio
async def test_get_child_client_validates_state(make_make_simple_mcp):
    """Test that get_child_client validates mount state."""
    backend = make_make_simple_mcp("backend")

    async with Compositor("test") as comp:
        await comp.mount_inproc("backend", backend)

        # Active mount: returns client
        client = comp.get_child_client("backend")
        assert client is not None

        # Unmount
        await comp.unmount_server("backend")

        # Inactive mount: raises
        with pytest.raises(ValueError, match="not mounted"):
            comp.get_child_client("backend")


@pytest.mark.asyncio
async def test_pinned_server_survives_close(make_make_simple_mcp):
    """Test that pinned servers remain after close()."""
    pinned = make_make_simple_mcp("pinned")

    async with Compositor("test") as comp:
        await comp.mount_inproc("pinned", pinned, pinned=True)

        # Verify mounted
        entries = await comp.server_entries()
        assert "pinned" in entries
        mount = comp._mounts["pinned"]
        assert mount.is_active

    # After close: pinned server still active
    entries = await comp.server_entries()
    assert "pinned" in entries
    mount = comp._mounts["pinned"]
    assert mount.is_active
    assert not mount.is_closed


@pytest.mark.asyncio
async def test_compositor_warns_on_leak(make_make_simple_mcp):
    """Test that __del__ detects leaked compositors.

    Note: The actual warning emission is tested manually as pytest's warning
    capture doesn't work reliably with ResourceWarnings from __del__.
    This test verifies the leak detection logic is correct.
    """
    backend = make_make_simple_mcp("backend")

    # Create compositor without context manager
    comp = Compositor("test")
    await comp.mount_inproc("backend", backend)

    # Verify the compositor is in a state that would trigger a warning
    assert comp._state == CompositorState.CREATED  # Never entered context
    assert len([n for n, m in comp._mounts.items() if not m.pinned]) > 0  # Has non-pinned mounts

    # Mock warnings.warn to verify it would be called
    with patch("warnings.warn") as mock_warn:
        # Trigger __del__ manually
        comp.__del__()

        # Verify warning was called
        assert mock_warn.called
        call_args = mock_warn.call_args
        warning_msg = call_args[0][0]
        warning_category = call_args[0][1]

        assert "COMPOSITOR LEAK" in warning_msg
        assert "test" in warning_msg
        assert "was never used as context manager" in warning_msg
        assert warning_category is ResourceWarning
