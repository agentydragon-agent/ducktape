from pathlib import Path

import pygit2
import pytest

from adgn.llm.mcp.git_ro.server import (
    GIT_RO_SERVER_NAME,
    DiffFormat,
    DiffInput,
    ListSlice,
    make_git_ro_server,
)
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.mcp_manager import McpManager


@pytest.mark.asyncio
async def test_git_ro_stat_counts(tmp_path: Path) -> None:
    """Create a repo, make a staged change, call git_diff(format=stat) and assert additions/deletions."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = pygit2.init_repository(str(repo_dir), initial_head="main")

    # initial commit
    (repo_dir / "file.txt").write_text("line1\n")
    repo.index.add("file.txt")
    repo.index.write()
    sig = pygit2.Signature("Test", "test@example.com")
    tree_oid = repo.index.write_tree()
    repo.create_commit("HEAD", sig, sig, "initial", tree_oid, [])

    # modify and stage a non-trivial diff (add two lines)
    (repo_dir / "file.txt").write_text("line1\nline2\nline3\n")
    repo.index.add("file.txt")
    repo.index.write()

    spec = make_inproc_slot_spec(make_git_ro_server(repo_dir))

    async with McpManager({GIT_RO_SERVER_NAME: spec}) as mcp:
        sess = await mcp.get_session(GIT_RO_SERVER_NAME)
        # Call the git_diff tool with format=stat and staged=True
        payload = DiffInput(
            format=DiffFormat.STAT,
            staged=True,
            find_renames=True,
            list_slice=ListSlice(offset=0, limit=100),
        )
        # Pass the Pydantic model instance directly so FastMCP can validate types natively
        res = await sess.call_tool(name="git_diff", arguments={"payload": payload})

    # Extract structured content with concrete typed shape: {result: {type, result{items}}}
    out = res.structuredContent
    assert isinstance(out, dict)
    assert "result" in out
    inner = out["result"]
    assert isinstance(inner, dict)
    assert inner.get("type") == "stat"
    items = inner["result"]["items"]
    assert isinstance(items, list)

    assert items, "No stat items returned"

    # Find our file entry and assert additions > 0
    two_lines = 2  # test clarity: two added lines expected
    for it in items:
        path = it.get("path") if isinstance(it, dict) else getattr(it, "path", None)
        if path == "file.txt":
            additions = (
                it.get("additions")
                if isinstance(it, dict)
                else getattr(it, "additions", 0)
            )
            deletions = (
                it.get("deletions")
                if isinstance(it, dict)
                else getattr(it, "deletions", 0)
            )
            # Expect exactly two additions (two new lines) and zero deletions
            assert int(additions) == two_lines, (
                f"Expected additions==2 for file.txt, got {additions}"
            )
            assert int(deletions) == 0, (
                f"Expected deletions==0 for file.txt, got {deletions}"
            )
            return

    pytest.fail("file.txt not found in stat items")
