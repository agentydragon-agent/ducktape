import os
from pathlib import Path

import pytest

from ..conftest import kill_daemon_and_verify
from ..test_utils import run_cli_command


@pytest.fixture
def real_env_with_post_script(real_temp_repo, config_factory, tmp_path):
    kill_daemon_and_verify(real_temp_repo)
    script = tmp_path / "post_create.sh"
    script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nwt=""\nfor a in "$@"; do case "$a" in --worktree_root=*) wt="${a#*=}";; esac; done\nif [[ -z "$wt" ]]; then echo "missing --worktree_root" >&2; exit 2; fi\ntouch "$wt/.post_create_ran"\n',
    )
    script.chmod(0o755)
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=False, post_creation_script=str(script))
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
    yield env, real_temp_repo
    kill_daemon_and_verify(real_temp_repo)


def test_post_creation_script_runs(real_env_with_post_script):
    env, repo = real_env_with_post_script
    name = "hooked"
    result = run_cli_command(["sh", "-c", name], env=env, timeout=15.0)
    assert result.returncode == 0
    wt_path = Path(repo) / "worktrees" / name
    assert wt_path.exists()
    assert (wt_path / ".post_create_ran").exists()
