"""E2E test: real wt daemon/client, mocked PyGithub via import shadowing, assert PR is shown.

Uses real repo/daemon environment; we inject a temporary 'github' module on PYTHONPATH
so the daemon imports our stub instead of the real PyGithub. This avoids network while
exercising the full daemon/CLI pipeline.
"""

import os
import re

import pytest

from ..test_utils import add_project_root_to_env, run_cli_command


@pytest.fixture(autouse=True)
def _no_gh_token(monkeypatch):
    from wt.server import github_client
    monkeypatch.setattr(github_client, "get_github_token", lambda *a, **kw: None)


@pytest.mark.integration
@pytest.mark.real_github
def test_github_pr_display_with_mocked_pygithub(
    real_temp_repo,
    config_factory,
    tmp_path,
):
    # Prepare config with GitHub enabled
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=True, github_repo="test/test")

    # Create a shadow 'github' package in a temp dir that provides Github stub
    mock_root = tmp_path / "mockpkgs"
    (mock_root / "github").mkdir(parents=True)
    (mock_root / "github" / "__init__.py").write_text(
        """
class _MockPR:
    def __init__(self):
        self.number = 123
        self.state = "open"
        self.draft = False
        self.mergeable = True
        self.merged_at = None
        self.additions = 10
        self.deletions = 2

class _MockRepo:
    def get_pull(self, number):
        return _MockPR()

class Github:
    def __init__(self, *args, **kwargs):
        pass
    def get_repo(self, full_name):
        return _MockRepo()
    def search_issues(self, q):
        # Return objects with .number attribute
        class _Issue: pass
        i = _Issue(); i.number = 123
        return [i]
""",
    )

    # Build environment inheriting system env to ensure click, etc. are available
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
    # Prepend our mock to PYTHONPATH so daemon imports it; also include project root
    existing = env.get("PYTHONPATH", "")
    add_project_root_to_env(env)
    env["PYTHONPATH"] = (
        f"{mock_root}:{env['PYTHONPATH']}"
        if existing or env.get("PYTHONPATH")
        else str(mock_root)
    )

    # Start daemon implicitly by running status once
    out = run_cli_command(["sh"], env=env, timeout=30.0)
    assert out.returncode == 0

    # Create a worktree with branch 'feature-x'
    out2 = run_cli_command(["sh", "-c", "feature-x"], env=env, timeout=30.0)
    assert out2.returncode == 0

    # Poll until output shows #123 and open and +10/-2
    import time

    deadline = time.time() + 12.0
    last = ""
    while time.time() < deadline:
        r = run_cli_command(["sh"], env=env, timeout=30.0)
        assert r.returncode == 0
        last = r.stdout
        if "#123" in last and re.search(r"\bcan merge\b", last) and "+10/-2" in last:
            break
        time.sleep(0.25)
    else:
        raise AssertionError(f"PR details not shown in time. Last output:\n{last}")
