"""E2E: real daemon/client + shadowed PyGithub; PR variants: open(can merge), merged, closed, no PR."""

import json
import os
from pathlib import Path
import re
import socket
import uuid

import pytest

from ..test_utils import add_project_root_to_env, run_cli_command

# Global conftest disables gh token via get_github_token


def _write_shadow_github(mock_root: Path, variant: str):
    mock_pkg = mock_root / "github"
    mock_pkg.mkdir(parents=True, exist_ok=True)
    if variant == "open_mergeable":
        body = """
from types import SimpleNamespace as NS
class Github:
    def __init__(self, *args, **kwargs):
        pass
    def get_repo(self, full_name):
        def get_pull(number):
            return NS(number=123, state="open", draft=False, mergeable=True, merged_at=None, additions=10, deletions=2)
        return NS(get_pull=get_pull)
    def search_issues(self, q):
        return [NS(number=123)]
"""
    elif variant == "merged":
        body = """
from types import SimpleNamespace as NS
import datetime as _dt
class Github:
    def __init__(self, *args, **kwargs):
        pass
    def get_repo(self, full_name):
        def get_pull(number):
            return NS(
                number=456,
                state="closed",
                draft=False,
                mergeable=True,
                merged_at=_dt.datetime.now(),
                additions=3,
                deletions=1,
            )
        return NS(get_pull=get_pull)
    def search_issues(self, q):
        return [NS(number=456)]
"""
    elif variant == "closed":
        body = """
from types import SimpleNamespace as NS
class Github:
    def __init__(self, *args, **kwargs):
        pass
    def get_repo(self, full_name):
        def get_pull(number):
            return NS(
                number=789,
                state="closed",
                draft=False,
                mergeable=False,
                merged_at=None,
                additions=4,
                deletions=4,
            )
        return NS(get_pull=get_pull)
    def search_issues(self, q):
        return [NS(number=789)]
"""
    elif variant == "none":
        body = """
from types import SimpleNamespace as NS
class Github:
    def __init__(self, *args, **kwargs):
        pass
    def get_repo(self, full_name):
        return NS()
    def search_issues(self, q):
        return []
"""
    else:
        raise ValueError("unknown variant")
    (mock_pkg / "__init__.py").write_text(body)


def _rpc_json(sock_path: str | os.PathLike, method: str, params: dict) -> dict:
    """Minimal JSON-RPC 2.0 call helper for tests over UNIX socket."""
    req = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": str(uuid.uuid4()),
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(sock_path))
        with s.makefile("rwb") as f:
            payload = (json.dumps(req) + "\n").encode()
            f.write(payload)
            f.flush()
            line = f.readline()
            if not line:
                raise AssertionError("No response from daemon")
            return json.loads(line.decode())


@pytest.mark.integration
@pytest.mark.parametrize(
    ("variant", "expects"),
    [
        ("open_mergeable", ["#123", "can merge", "+10/-2"]),
        ("merged", ["#456", "merged", "+3/-1"]),
        ("closed", ["#789", "closed", "+4/-4"]),
        ("none", []),
    ],
)
def test_github_pr_variants(real_temp_repo, config_factory, tmp_path, variant, expects):
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=True, github_repo="test/test")

    mock_root = tmp_path / "mockpkgs"
    _write_shadow_github(mock_root, variant)

    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
    add_project_root_to_env(env)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{mock_root}:{existing}" if existing else str(mock_root)

    # Start daemon
    r1 = run_cli_command(["sh"], env=env, timeout=30.0)
    assert r1.returncode == 0

    # Create a worktree and wait for PR display
    r2 = run_cli_command(["sh", "-c", "feature-x"], env=env, timeout=30.0)
    assert r2.returncode == 0

    # Lookup wtid and force a PR refresh synchronously via RPC to avoid polling
    wt_by_name = _rpc_json(
        config.daemon_socket_path,
        "worktree_get_by_name",
        {"name": "feature-x"},
    )
    wtid = wt_by_name["result"]["wtid"]
    assert wtid, "Server did not return wtid for created worktree"
    refresh_res = _rpc_json(config.daemon_socket_path, "pr_refresh_now", {"wtid": wtid})
    assert refresh_res.get("result") == "ok"

    # Render once and assert
    out = run_cli_command(["sh"], env=env, timeout=30.0).stdout
    if expects:
        for x in expects:
            assert x in out
    else:
        # No PR should render no #<n>
        assert not re.search(r"#\d+", out)
