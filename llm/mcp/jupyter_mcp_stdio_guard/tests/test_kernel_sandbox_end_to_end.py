import sys
from pathlib import Path

import pytest
import os
import shutil
import policy_fixture as policy


# These tests use the same explicit YAML policy used by the wrapper.
# The helper in policy_fixture.py can be a template for users who want to
# generate sandbox configs programmatically for their own workspaces.


def _build_wrapper_cmd(ws: Path, run_root: Path, port: int) -> list[str]:
    # wrapper delegates sandboxing to sandboxer; pass YAML and keep trace enabled for diagnostics
    return [
        sys.executable,
        "-m",
        "jupyter_mcp_stdio_guard.wrapper",
        "stdio",
        "--policy-config",
        str(ws / ".sandbox_jupyter.yaml"),
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


@pytest.mark.macos
@pytest.mark.parametrize(
    "provision_ws_with_policy,net_mode,expect_http",
    [pytest.param({"net": "loopback"}, "loopback", False, id="loopback"), pytest.param({"net": "open"}, "open", True, id="open")],
    indirect=["provision_ws_with_policy"],
)
def test_network_modes_http_boundary(
    provision_ws_with_policy,
    net_mode,
    expect_http,
    pick_free_port,
    mcp_call_tool,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
):
    if sys.platform != "darwin":
        pytest.skip("macOS seatbelt only")
    assert shutil.which("jupyter") and shutil.which("jupyter-mcp-server")

    (ws, run_root) = provision_ws_with_policy
    # policy created by fixture already correct by indirect parametrization

    port = pick_free_port
    cmd = _build_wrapper_cmd(ws, run_root, port)

    with launch_proc(cmd, env_update=pkg_src_env_update) as proc:
        code = (
            "import urllib.request\n"
            "try:\n"
            "    with urllib.request.urlopen('http://example.com', timeout=6) as r:\n"
            "        data = r.read(100).decode('utf-8', 'ignore')\n"
            "    print('NET_OK:', 'Example Domain' in data)\n"
            "except Exception as e:\n"
            "    print('NET_FAIL:', type(e).__name__)\n"
        )
        result = mcp_call_tool(
            proc, "append_execute_code_cell", {"cell_source": code}, call_timeout=60.0
        )
        blob = str(result)
        if expect_http:
            assert "NET_OK:" in blob or "Example Domain" in blob, blob
        else:
            assert "NET_FAIL:" in blob and "NET_OK:" not in blob, blob


@pytest.mark.macos
@pytest.mark.parametrize(
    "provision_ws_with_policy",
    [pytest.param({"env_set": {"FOO_SET": "SET_OK"}, "env_passthrough": ["BAR_PASS"], "net": "loopback"}, id="env")],
    indirect=["provision_ws_with_policy"],
)
def test_env_set_and_passthrough_visible_in_kernel(
    provision_ws_with_policy,
    pick_free_port,
    mcp_call_tool,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
):
    if sys.platform != "darwin":
        pytest.skip("seatbelt kernel sandbox only on macOS")

    (ws, run_root) = provision_ws_with_policy
    # policy created by fixture already correct using marker; nothing to overwrite

    port = pick_free_port
    cmd = _build_wrapper_cmd(ws, run_root, port)

    env_update = dict(pkg_src_env_update)
    env_update["BAR_PASS"] = "PASS_OK"

    with launch_proc(cmd, env_update=env_update) as proc:
        code = (
            "import os\n"
            "print('ENV_FOO_SET=', os.environ.get('FOO_SET'))\n"
            "print('ENV_BAR_PASS=', os.environ.get('BAR_PASS'))\n"
        )
        result = mcp_call_tool(
            proc, "append_execute_code_cell", {"cell_source": code}, call_timeout=45.0
        )
        blob = str(result)
        assert "ENV_FOO_SET= SET_OK" in blob and "ENV_BAR_PASS= PASS_OK" in blob, blob


@pytest.mark.macos
@pytest.mark.parametrize(
    "provision_ws_with_policy",
    [pytest.param({}, id="fs")],
    indirect=["provision_ws_with_policy"],
)
def test_fs_read_allow_and_deny(
    tmp_path,
    provision_ws_with_policy,
    pick_free_port,
    mcp_call_tool,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
):
    if sys.platform != "darwin":
        pytest.skip("seatbelt kernel sandbox only on macOS")

    (ws, run_root) = provision_ws_with_policy

    allowed_dir = tmp_path / "allowed"; denied_dir = tmp_path / "denied"
    allowed_dir.mkdir(); denied_dir.mkdir()
    (allowed_dir / "ok.txt").write_text("OK_FILE")
    (denied_dir / "no.txt").write_text("NO_FILE")

    # Re-write policy to explicitly allow only allowed_dir reads (deny others)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    venv_root = Path(sys.executable).resolve().parent.parent
    venv_virtual = Path(sys.executable).parent.parent  # non-resolved virtualenv root
    policy.write_policy(
        ws,
        run_root,
        allow_read_all=False,
        add_read_paths=[
            # minimally required for sandbox/Jupyter to function
            ws.as_posix(),
            run_root.as_posix(),
            # test-specific allow
            allowed_dir.as_posix(),
            # kernel venv binary path (virtualenv symlink tree) and resolved uv install
            venv_virtual.as_posix(),
            (venv_virtual / "bin").as_posix(),
            venv_root.as_posix(),
            (venv_root / "bin").as_posix(),
            (venv_root / "lib").as_posix(),
            (venv_root / "lib" / f"python{ver}").as_posix(),
            (venv_root / "lib" / f"python{ver}" / "site-packages").as_posix(),
        ],
        net="loopback",
    )

    port = pick_free_port
    cmd = _build_wrapper_cmd(ws, run_root, port)

    with launch_proc(cmd, env_update=pkg_src_env_update) as proc:
        code = (
            f"print('READ_OK=', open('{(allowed_dir / 'ok.txt').as_posix()}', 'r').read().strip())\n"
            f"import sys\n"
            f"try:\n"
            f"    open('{(denied_dir / 'no.txt').as_posix()}', 'r').read()\n"
            f"    print('READ_DENY_OOPS')\n"
            f"except Exception as e:\n"
            f"    print('READ_DENY=', type(e).__name__)\n"
        )
        result = mcp_call_tool(
            proc, "append_execute_code_cell", {"cell_source": code}, call_timeout=60.0
        )
        blob = str(result)
        assert "READ_OK= OK_FILE" in blob and "READ_DENY=" in blob and "READ_DENY_OOPS" not in blob, blob
