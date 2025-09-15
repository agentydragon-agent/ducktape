from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import pygit2

from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mcp.git_ro.server import make_git_ro_server, GIT_RO_SERVER_NAME
from adgn_llm.mini_codex.mcp_manager import McpManager


def _ensure_identity(repo: pygit2.Repository) -> None:
    cfg = repo.config
    cfg["user.name"] = "Test"
    cfg["user.email"] = "test@example.com"


def _commit_all(repo: pygit2.Repository, message: str) -> str:
    idx = repo.index
    idx.add_all()
    idx.write()
    tree = idx.write_tree()
    parents: list[pygit2.Oid] = []
    if not repo.head_is_unborn:
        parents = [repo.head.target]
    author = committer = pygit2.Signature("Test", "test@example.com")
    oid = repo.create_commit("HEAD", author, committer, message, tree, parents)
    return str(oid)


@pytest.fixture()
def repo_git_ro(tmp_path: Path) -> Path:
    """Single unified repo for git-ro tests.

    Commits:
      1) README
      2) add file1
      3) rename file1 -> file_renamed.txt + modify
    Also stages a large big.txt (uncommitted) for diff pagination tests.
    """
    repo_path = tmp_path / "repo_git_ro"
    repo_path.mkdir(parents=True, exist_ok=True)
    repo = pygit2.init_repository(str(repo_path), bare=False)
    _ensure_identity(repo)

    (repo_path / "README.md").write_text("hello\n", encoding="utf-8")
    _commit_all(repo, "init")

    (repo_path / "file1.txt").write_text("hello\n", encoding="utf-8")
    _commit_all(repo, "add file1")

    (repo_path / "file1.txt").rename(repo_path / "file_renamed.txt")
    (repo_path / "file_renamed.txt").write_text("hello world\n", encoding="utf-8")
    _commit_all(repo, "rename + modify")

    big = repo_path / "big.txt"
    big.write_text("\n".join(f"line {i}" for i in range(20000)) + "\n", encoding="utf-8")
    idx = repo.index
    idx.add(str(big.relative_to(repo_path)))
    idx.write()

    return repo_path


@pytest_asyncio.fixture()
async def git_ro_session(repo_git_ro: Path):
    """Async session fixture: opens/closes the MCP manager within the same task.

    Yields a tuple (m, sess) for tests to call tools safely.
    """
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        yield m, sess
