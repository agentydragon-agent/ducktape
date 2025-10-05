import os
import shutil

import pytest

# Run these stdio-handshake tests in a dedicated xdist group to avoid flakiness
pytestmark = [pytest.mark.xdist_group("sj_stdio")]

# Mark xfail if external tooling is not available
if not shutil.which("jupyter-mcp-server"):
    pytestmark.append(pytest.mark.xfail(reason="jupyter-mcp-server not installed", strict=False))
if os.environ.get("ADGN_RUN_SJ_STDIO") != "1":
    pytestmark.append(
        pytest.mark.skip(
            reason="SJ stdio integration requires external tooling; set ADGN_RUN_SJ_STDIO=1 to run"
        )
    )


def test_wrapper_unsandbox_initialize_and_hello(
    provision_ws_with_policy,
    pick_free_port,
    mcp_stdio_protocol,
    pkg_src_env_update,
    launch_proc,
):
    (ws, run_root) = provision_ws_with_policy
    port = pick_free_port
    cmd = [
        "sandbox-jupyter",
        "--workspace",
        str(ws),
        "--run-root",
        str(run_root),
        "--mode",
        "seatbelt",
        "--jupyter-port",
        str(port),
        "--no-kernel-sandbox",
    ]
    with launch_proc(cmd, env_update=pkg_src_env_update) as proc:
        result = mcp_stdio_protocol(
            proc.stdin,
            proc.stdout,
            "append_execute_code_cell",
            {"cell_source": "print('hello world')"},
            timeout=30.0,
        )
        assert "hello world" in str(result)
