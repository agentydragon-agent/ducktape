import sys
from pathlib import Path

import pytest
import os
import shutil
import policy_fixture as policy


# These tests use the same explicit YAML policy used by the wrapper.
# The helper in policy_fixture.py can be a template for users who want to
# generate sandbox configs programmatically for their own workspaces.

@pytest.mark.macos
def test_kernel_is_sandboxed_env_and_policy(
    provision_ws_with_policy,
    pick_free_port,
    mcp_stdio_protocol,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
):
    if sys.platform != "darwin":
        pytest.skip("macOS seatbelt only")
    # Ensure jupyter binaries are resolvable from child according to explicit env
    assert shutil.which("jupyter") and shutil.which("jupyter-mcp-server")

    (ws, run_root) = provision_ws_with_policy

    port = pick_free_port

    cmd = [
        "sandbox-jupyter-mcp",
        "--workspace",
        str(ws),
        "--run-root",
        str(run_root),
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


@pytest.mark.macos
def test_write_outside_workspace_denied(
    provision_ws_with_policy,
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

    (ws, run_root) = provision_ws_with_policy

    outside_dir = tmp_path.parent / (tmp_path.name + "_outside")
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "denied.txt"

    port = pick_free_port

    cmd = [
        "sandbox-jupyter-mcp",
        "--workspace",
        str(ws),
        "--run-root",
        str(run_root),
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
        result = mcp_call_tool(
            proc, "append_execute_code_cell", {"cell_source": code}, call_timeout=60.0
        )
        # Expect failure: kernel error reported in content; not a silent success
        text_blob = str(result)
        assert (
            "Permission" in text_blob or "Operation not permitted" in text_blob or "Errno" in text_blob
        ), text_blob
        assert "wrote OUTSIDE" not in text_blob
