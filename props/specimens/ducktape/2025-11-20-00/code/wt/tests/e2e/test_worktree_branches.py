import os

import pygit2
import pytest

from wt.shared.git_utils import git_run

pytestmark = pytest.mark.timeout(10)


def test_worktree_branch_names_are_actual(repo_factory, config_factory, wtcli):
    repo_path = repo_factory.create_repo()
    cfg = config_factory(repo_path).minimal(upstream_branch="HEAD")

    # Create two worktrees against branches test/aaaaa and test/bbbbb
    repo = pygit2.Repository(str(repo_path))
    head = repo.head.target
    repo.create_branch("test/aaaaa", repo.get(head))
    repo.create_branch("test/bbbbb", repo.get(head))

    wt_a = repo_path / "worktrees" / "aaaaa"
    wt_b = repo_path / "worktrees" / "bbbbb"

    git_run(["worktree", "add", str(wt_a), "test/aaaaa"], cwd=repo_path)
    git_run(["worktree", "add", str(wt_b), "test/bbbbb"], cwd=repo_path)

    # Use GitManager via daemon handlers indirectly by calling CLI ls (list)
    env = os.environ.copy()
    env["WT_DIR"] = str(cfg.wt_dir)

    # Start daemon by calling status once
    wtcli(env).status()

    # Call list command and ensure worktrees are present (ls output shows names/paths)
    res = wtcli(env).sh("ls")
    assert res.returncode == 0
    out = res.stdout
    assert "aaaaa:" in out
    assert "bbbbb:" in out

    # Additionally, query actual worktree branch heads (branch can change over time)
    repo_a = pygit2.Repository(str(wt_a))
    repo_b = pygit2.Repository(str(wt_b))
    assert repo_a.head.shorthand == "test/aaaaa"
    assert repo_b.head.shorthand == "test/bbbbb"
