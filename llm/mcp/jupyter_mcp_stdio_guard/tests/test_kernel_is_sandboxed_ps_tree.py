import sys

import pytest


def test_kernel_is_sandboxed_ps_tree(
    tmp_path,
    pick_free_port,
    mcp_stdio_protocol,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
):
    if sys.platform != "darwin":
        pytest.skip("macOS seatbelt only")

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    port = pick_free_port

    cmd = [
        sys.executable,
        "-m",
        "jupyter_mcp_stdio_guard",
        "--workspace",
        str(ws),
        "--mode",
        "seatbelt",
        "--jupyter-port",
        str(port),
        "--trace-sandbox",
    ]

    with launch_proc(cmd, env_update=pkg_src_env_update) as proc:
        code = (
            "import os, subprocess\n"
            "print('ENV_SANDBOXED=', os.environ.get('SJ_KERNEL_SANDBOXED'))\n"
            "print('POLICY_PATH=', os.environ.get('SJ_POLICY_PATH'))\n"
        )
        result = mcp_stdio_protocol(
            proc.stdin,
            proc.stdout,
            "append_execute_code_cell",
            {"cell_source": code},
            timeout=45.0,
        )
        text = str(result)
        assert "ENV_SANDBOXED= 1" in text
        assert "POLICY_PATH=" in text
