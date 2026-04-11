"""Shared fixtures for hook daemon tests."""

import shutil
import tempfile
import uuid
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import pygit2
import pytest
import yaml

from devinfra.claude.hook_daemon.testing.testing_helpers import PROFILE_FILENAME, setup_daemon_project
from devinfra.claude.session_paths import SessionPaths
from util.testing.undeclared_outputs import undeclared_outputs_dir


def init_git_repo(repo_path: Path) -> None:
    """Initialize a git repo at repo_path with all files committed."""
    repo = pygit2.init_repository(str(repo_path))
    repo.config["user.name"] = "Test"
    repo.config["user.email"] = "test@test.com"
    repo.index.add_all()
    repo.index.write()
    tree = repo.index.write_tree()
    sig = pygit2.Signature("Test", "test@test.com")
    repo.create_commit("HEAD", sig, sig, "init", tree, [])


def write_precommit_config(repo_path: Path, hooks: Sequence[dict[str, Any]]) -> None:
    """Write a .pre-commit-config.yaml with local system hooks."""
    config = {"repos": [{"repo": "local", "hooks": list(hooks)}]}
    (repo_path / ".pre-commit-config.yaml").write_text(yaml.dump(config))


@pytest.fixture
def short_tmp() -> Generator[Path]:
    """Short temp dir to avoid AF_UNIX 108-byte path limit in Bazel sandboxes."""
    with tempfile.TemporaryDirectory(prefix="hd-", dir="/tmp") as d:
        yield Path(d)


@pytest.fixture
def daemon_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[SessionPaths]:
    """SessionPaths with a unique session_id (isolates socket path between tests).

    Each test gets its own session_id, so daemon socket paths don't collide.
    Daemons left running after a test are harmless — they'll be killed when
    the RBE container exits.

    Sets CLAUDE_PROJECT_DIR and DUCKTAPE_CLAUDE_HOOKS_PROFILE so the daemon
    can load profile config at startup.

    After the test, copies daemon logs to undeclared test outputs for post-hoc debugging.
    """
    session_id = f"td-{uuid.uuid4().hex[:8]}"
    paths = SessionPaths(session_id=session_id, home=tmp_path, xdg_cache_home=tmp_path / "cache")
    (tmp_path / "cache").mkdir()

    project_dir, env_file = setup_daemon_project(tmp_path, paths)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(env_file))
    monkeypatch.setenv("DUCKTAPE_CLAUDE_HOOKS_PROFILE", f".claude_hooks/{PROFILE_FILENAME}")

    yield paths

    # Copy daemon logs to undeclared outputs for BuildBuddy retrieval.
    daemon_dir = paths.hook_daemon_dir
    if daemon_dir.exists():
        out_dir = undeclared_outputs_dir() / request.node.name
        out_dir.mkdir(parents=True, exist_ok=True)
        for log_file in daemon_dir.glob("*.log"):
            shutil.copy2(log_file, out_dir / log_file.name)
