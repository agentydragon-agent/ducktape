import sys
from pathlib import Path

import pytest


def test_kernel_write_outside_workspace_denied(
    tmp_path,
    pick_free_port,
    mcp_stdio_protocol,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
    collect_mcp_logs_fn,
):
    if sys.platform != "darwin":
        pytest.skip("seatbelt kernel sandbox only on macOS")

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "denied.txt"

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
            "import pathlib\n"
            f"path = pathlib.Path(r'''{outside_file}''')\n"
            "try:\n"
            "    path.write_text('x')\n"
            "    print('wrote OUTSIDE')\n"
            "except Exception as e:\n"
            "    import sys\n"
            "    print(type(e).__name__, str(e))\n"
        )
        result = mcp_stdio_protocol(
            proc.stdin,
            proc.stdout,
            "append_execute_code_cell",
            {"cell_source": code},
            timeout=45.0,
        )
        # Expect failure: permission error, not success
        assert result.get("isError") is True
        text_blob = str(result)
        if not (
            "Permission" in text_blob or "Operation not permitted" in text_blob or "Errno" in text_blob
        ):
            out, err = collect_mcp_logs_fn()
            pytest.fail(f"Unexpected result: {text_blob}\nMCP logs:\n{out}\n{err}")
