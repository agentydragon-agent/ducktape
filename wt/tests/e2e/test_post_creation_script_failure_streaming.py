import os
from pathlib import Path

import pytest

from ..test_utils import run_cli_command


@pytest.fixture
def failing_env(real_temp_repo, config_factory, tmp_path):
    # Clean state ensured by per-test WT_DIR via fixtures
    script = tmp_path / "post_create_fail.sh"
    script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\necho "hello from setup"\n>&2 echo "setup error"\nexit 42\n',
    )
    script.chmod(0o755)
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=False, post_creation_script=str(script))
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
    yield env, real_temp_repo
    # Cleanup handled by fixture


def test_post_creation_script_failure_is_streamed_and_nonzero(failing_env):
    env, repo = failing_env
    name = "hooked-fail"
    result = run_cli_command(["sh", "-c", name], env=env, timeout=20.0)
    assert result.returncode != 0
    assert "hello from setup" in (result.stdout or "") + (result.stderr or "")
    assert "setup error" in (result.stdout or "") + (result.stderr or "")
    assert "Post-creation script failed" in (result.stdout or "") + (
        result.stderr or ""
    )
    wt_path = Path(repo) / "worktrees" / name
    assert wt_path.exists()
