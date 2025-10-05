from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

# Run these stdio-handshake tests in a dedicated xdist group to avoid flakiness
pytestmark = [pytest.mark.xdist_group("sj_stdio")]

# Mark xfail if external tooling is not available
if not shutil.which("jupyter-mcp-server"):
    pytestmark.append(pytest.mark.xfail(reason="jupyter-mcp-server not installed", strict=False))
# Allow opt-in to actually run these heavy integration tests.
if os.environ.get("ADGN_RUN_SJ_STDIO") != "1":
    pytestmark.append(
        pytest.mark.skip(
            reason="SJ stdio integration requires external tooling; set ADGN_RUN_SJ_STDIO=1 to run"
        )
    )

# Ensure required jupyter kernel/server packages are present — with pyproject deps these should be installed


@pytest.mark.macos
@pytest.mark.shell
@pytest.mark.asyncio
async def test_kernel_runs_minimal(
    tmp_path: Path, launch_proc, mcp_stdio_protocol, pkg_src_env_update
):
    run = tmp_path
    ws = run / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "workspace").mkdir(parents=True, exist_ok=True)
    env = pkg_src_env_update

    cmd = [
        "sandbox-jupyter",
        "seatbelt",
        ws,
        "--run-root",
        run / ".mcp",
        "--policy",
        run / "policy.yaml",
        "--kernel-python",
        os.environ.get("PYTHON", "python3"),
        "--jupyter-port",
        0,
    ]
    # Write a minimal policy.yaml
    (run / "policy.yaml").write_text(
        """
env:
  set:
    HOME: {home}
fs:
  read_paths: ['/']
  write_paths: ['{home}']
net: {{ mode: loopback }}
""".format(home=str(run)),
        encoding="utf-8",
    )

    with launch_proc(cmd, env_update=env) as proc:
        res = mcp_stdio_protocol(
            proc.stdin,
            proc.stdout,
            "append_execute_code_cell",
            {"cell_source": "print('OK')"},
            timeout=45.0,
        )
        assert "result" in (res or {})
