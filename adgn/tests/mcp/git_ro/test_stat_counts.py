from pathlib import Path

import pygit2
import pytest

from adgn.mcp.git_ro.server import GIT_RO_SERVER_NAME, DiffFormat, DiffInput, ListSlice, make_git_ro_server


@pytest.mark.asyncio
async def test_git_ro_stat_counts(tmp_path: Path, make_typed_mcp) -> None:
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

    server = make_git_ro_server(repo_dir)

    async with make_typed_mcp(server, GIT_RO_SERVER_NAME) as (client, session):
        # Call the git_diff tool with format=stat and staged=True
        result = await client.git_diff(
            DiffInput(format=DiffFormat.STAT, staged=True, find_renames=True, list_slice=ListSlice(offset=0, limit=100))
        )

        # result is a flattened StatResult (DiffStatPage fields directly available)
        items = result.items
        assert isinstance(items, list)

        for it in items:
            if it.path == "file.txt":
                assert int(it.additions) == 2, f"Expected additions==2 for file.txt, got {it.additions}"
                assert int(it.deletions) == 0, f"Expected deletions==0 for file.txt, got {it.deletions}"
                break
        else:
            pytest.fail("file.txt not found in stat items")
