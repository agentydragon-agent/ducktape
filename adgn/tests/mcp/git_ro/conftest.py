from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import pygit2
import pytest

from adgn.mcp.git_ro.server import make_git_ro_server, GIT_RO_SERVER_NAME
from adgn.mcp.inproc_transport import make_inproc_slot_spec


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


@pytest.fixture
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
    big.write_text(
        "\n".join(f"line {i}" for i in range(20000)) + "\n",
        encoding="utf-8",
    )
    idx = repo.index
    idx.add(str(big.relative_to(repo_path)))
    idx.write()

    return repo_path


@pytest.fixture
def git_ro_session(repo_git_ro: Path):
    """Factory fixture returning an async context manager that yields an initialized ClientSession.

    Usage in tests:
        async with git_ro_session() as session:
            ...
    Ensures enter/exit occur in the same task to satisfy anyio cancel-scope rules.
    """
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))

    @asynccontextmanager
    async def _open():
        async with AsyncExitStack() as stack:
            slot = await spec.open(stack)
            yield slot.session

    return _open


@pytest.fixture
def typed_git_ro(repo_git_ro: Path, make_typed_mcp):
    server = make_git_ro_server(repo_git_ro)

    @asynccontextmanager
    async def _open():
        async with make_typed_mcp(server, GIT_RO_SERVER_NAME) as pair:
            yield pair

    return _open
