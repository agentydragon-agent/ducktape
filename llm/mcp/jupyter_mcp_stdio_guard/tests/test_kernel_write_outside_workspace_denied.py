import sys
from pathlib import Path

import pytest


def test_kernel_write_outside_workspace_denied(
    tmp_path,
    pick_free_port,
    mcp_call_tool,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
    collect_mcp_logs_fn,
):
    if sys.platform != "darwin":
        pytest.skip("seatbelt kernel sandbox only on macOS")

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    outside_dir = tmp_path.parent / (tmp_path.name + "_outside")
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "denied.txt"

    port = pick_free_port

    cmd = [
        "sandbox-jupyter-mcp",
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
            "import pathlib\n"
            f"pathlib.Path('{outside_file}').write_text('x')\n"
        )
        result = mcp_call_tool(proc, "append_execute_code_cell", {"cell_source": code}, call_timeout=60.0)
        # Expect failure: kernel error reported in content; not a silent success
        text_blob = str(result)
        assert (
            "Permission" in text_blob or "Operation not permitted" in text_blob or "Errno" in text_blob
        ), text_blob
        assert "wrote OUTSIDE" not in text_blob
