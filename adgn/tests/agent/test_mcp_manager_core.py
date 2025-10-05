from __future__ import annotations

from mcp import types as mcp_types
import pytest

from adgn.agent.mcp_manager import McpManager


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
    # Exercise cache semantics via public list_tools + explicit invalidation.
    m = McpManager(specs={}, eager_open=False)
    async with m:
        # Stub sessions per server that return configurable tool lists
        class StubSession:
            def __init__(self, tools: list[mcp_types.Tool]):
                self._tools = tools

            async def list_tools(self) -> mcp_types.ListToolsResult:  # type: ignore[override]
                return mcp_types.ListToolsResult(tools=self._tools)

        git_v1 = [mcp_types.Tool(name="git_diff", description="", inputSchema={})]
        edit_v1 = [mcp_types.Tool(name="read", description="", inputSchema={})]

        sessions: dict[str, StubSession] = {
            "git-ro": StubSession(git_v1),
            "editor": StubSession(edit_v1),
        }

        async def fake_get_session(name: str):  # type: ignore[no-untyped-def]
            return sessions[name]

        monkeypatch.setattr(m, "get_session", fake_get_session)

        def to_map(entries: list):
            out: dict[str, list[str]] = {}
            for e in entries:
                out.setdefault(e.server, []).append(e.tool.name)
            return out

        # First call populates caches
        res1 = await m.list_tools(only=["git-ro", "editor"])
        assert to_map(res1) == {"git-ro": ["git_diff"], "editor": ["read"]}

        # Change underlying sessions; cache should still serve old values
        sessions["git-ro"]._tools = [mcp_types.Tool(name="status", description="", inputSchema={})]
        sessions["editor"]._tools = [mcp_types.Tool(name="write", description="", inputSchema={})]
        res2 = await m.list_tools(only=["git-ro", "editor"])
        assert to_map(res2) == {"git-ro": ["git_diff"], "editor": ["read"]}

        # Invalidate one server; only that one refreshes
        m.invalidate_tools_cache_for("git-ro")
        res3 = await m.list_tools(only=["git-ro", "editor"])
        assert to_map(res3) == {"git-ro": ["status"], "editor": ["read"]}

        # Invalidate the other; both reflect updated underlying tool lists
        m.invalidate_tools_cache_for("editor")
        res4 = await m.list_tools(only=["git-ro", "editor"])
        assert to_map(res4) == {"git-ro": ["status"], "editor": ["write"]}
