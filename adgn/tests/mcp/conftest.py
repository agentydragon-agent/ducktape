from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess

from mcp.server.fastmcp import FastMCP
import pytest
import pytest_asyncio

from adgn.mcp.git_ro.server import GIT_RO_SERVER_NAME, make_git_ro_server
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.agent.mcp_manager import McpManager


@pytest.fixture
def git_run() -> Callable[[list[str], Path], None]:
    def _run(cmd: list[str], cwd: Path) -> None:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"cmd failed: {' '.join(cmd)}\n{proc.stderr or proc.stdout}",
            )

    return _run


@pytest.fixture
def git_repo_factory(
    tmp_path: Path,
    git_run: Callable[[list[str], Path], None],
) -> Callable[[str], Path]:
    def _make(name: str) -> Path:
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        git_run(["git", "init"], repo)
        git_run(["git", "config", "user.name", "Test"], repo)
        git_run(["git", "config", "user.email", "test@example.com"], repo)
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        git_run(["git", "add", "-A"], repo)
        git_run(["git", "commit", "-m", "init"], repo)
        return repo

    return _make


@pytest.fixture
def git_ro_server(git_repo_factory) -> FastMCP:
    """FastMCP read-only Git server bound to a single repo under tmp_path."""
    repo = git_repo_factory("repo-bound")
    return make_git_ro_server(repo)


@pytest_asyncio.fixture()
async def mcp_git_ro(git_ro_server: FastMCP) -> McpManager:
    """MCP manager for the read-only Git server (in-proc transport)."""
    spec = make_inproc_slot_spec(git_ro_server)
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        yield m


# --- Unified repo fixture for all git-ro tests ---
@pytest.fixture
def repo_git_ro(git_repo_factory, git_run) -> Path:
    repo: Path = git_repo_factory("repo_git_ro")
    # Commit 1: README from factory
    # Commit 2: add file1
    (repo / "file1.txt").write_text("hello\n", encoding="utf-8")
    git_run(["git", "add", "-A"], repo)
    git_run(["git", "commit", "-m", "add file1"], repo)
    # Commit 3: rename + modify
    (repo / "file1.txt").rename(repo / "file_renamed.txt")
    (repo / "file_renamed.txt").write_text("hello world\n", encoding="utf-8")
    git_run(["git", "add", "-A"], repo)
    git_run(["git", "commit", "-m", "rename + modify"], repo)
    # Staged large file (not committed) for diff pagination tests
    big = repo / "big.txt"
    big.write_text(
        "\n".join(f"line {i}" for i in range(20000)) + "\n",
        encoding="utf-8",
    )
    git_run(["git", "add", "-A"], repo)
    return repo


@pytest_asyncio.fixture()
async def git_ro_session(repo_git_ro: Path):
    spec = make_inproc_slot_spec(make_git_ro_server(repo_git_ro))
    async with McpManager({GIT_RO_SERVER_NAME: spec}) as m:
        sess = await m.get_session(GIT_RO_SERVER_NAME)
        yield m, sess
