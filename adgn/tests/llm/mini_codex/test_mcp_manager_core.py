from __future__ import annotations

import pytest

from adgn.llm.mini_codex.mcp_manager import McpManager


@pytest.mark.asyncio
async def test_poll_notifications_batches_and_clears():
    m = McpManager(specs={})
    async with m:
        # Simulate two updates on same (server, uri) and one on another server
        m.notify_resource_updated("git-ro", "http://a.txt")  # v1
        m.notify_resource_updated("git-ro", "http://a.txt")  # v2
        m.notify_resource_updated("editor", "file:///b.py")  # v1

        batch = m.poll_notifications()
        # Batch should contain two entries with latest versions
        by_server: dict[str, dict[str, int]] = {}
        for ev in batch.resources_updated:
            by_server.setdefault(ev.server, {})[ev.uri] = ev.version
        assert by_server == {
            "git-ro": {"http://a.txt": 2},
            "editor": {"file:///b.py": 1},
        }
        # Second poll returns empty
        empty = m.poll_notifications()
        assert empty.resources_updated == []


@pytest.mark.asyncio
async def test_invalidate_tools_cache_for_removes_entries(monkeypatch):
    # Prepare a manager with a fake server spec; we won't open sessions, only the cache dict
    m = McpManager(specs={})
    async with m:
        # Pre-populate per-server cache directly to simulate a prior list_tools call
        m._tools_cache_by_server["git-ro"] = [
            {
                "type": "function",
                "name": "mcp__git-ro__git_diff",
                "description": "",
                "parameters": {},
            },
        ]
        m._tools_cache_by_server["editor"] = [
            {
                "type": "function",
                "name": "mcp__editor__read",
                "description": "",
                "parameters": {},
            },
        ]
        assert "git-ro" in m._tools_cache_by_server
        assert "editor" in m._tools_cache_by_server

        # Invalidate one server
        m.invalidate_tools_cache_for("git-ro")
        assert "git-ro" not in m._tools_cache_by_server
        assert "editor" in m._tools_cache_by_server

        # Invalidate multiple via varargs
        m.invalidate_tools_cache_for("editor")
        assert m._tools_cache_by_server == {}
