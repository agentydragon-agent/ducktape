from __future__ import annotations

import os
from pathlib import Path

import pygit2
import pytest
import yaml

from adgn.wt.server.pr_service import PRCacheError, PRService
from adgn.wt.server.types import DiscoveredWorktree
from adgn.wt.shared.configuration import Configuration


class DummyGitManager:
    def get_repo(self, path: Path):
        # Simulate a gone/missing worktree path
        raise pygit2.GitError(f"Repository not found at {path}")


def _make_real_config(tmp_path: Path) -> Configuration:
    wt_dir = tmp_path / "wt"
    wt_dir.mkdir()

    main_repo = tmp_path / "main_repo"
    main_repo.mkdir()
    # Initialize a real git repo so Configuration.resolve passes
    pygit2.init_repository(str(main_repo), bare=False)

    worktrees_dir = tmp_path / "worktrees"
    worktrees_dir.mkdir()

    # Minimal viable config.yaml (use proper YAML serialization)
    config_data = {
        "main_repo": str(main_repo),
        "worktrees_dir": str(worktrees_dir),
        "branch_prefix": "feature/",
        "upstream_branch": "main",
        "github_enabled": False,
        "github_repo": "",
    }
    (wt_dir / "config.yaml").write_text(yaml.safe_dump(config_data, sort_keys=False))

    os.environ["WT_TEST_MODE"] = "1"
    return Configuration.resolve(wt_dir)


@pytest.mark.asyncio
async def test_pr_service_handles_missing_worktree_without_crashing(tmp_path: Path):
    cfg = _make_real_config(tmp_path)

    prsvc = PRService(
        github_interface=None,  # GitHub disabled is fine for this unit test
        config=cfg,
        worktree_info=DiscoveredWorktree(
            path=Path("/nonexistent/worktree"),
            name="gone",
            wtid="gone-wtid",
        ),
        git_manager=DummyGitManager(),
    )

    # Should not raise; should mark cache as error and return
    await prsvc._refresh_github_cache("test", [])

    assert isinstance(prsvc.cached, PRCacheError)
    assert "Repository not found" in prsvc.cached.error
