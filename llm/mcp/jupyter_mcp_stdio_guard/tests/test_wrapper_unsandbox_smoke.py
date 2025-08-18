import sys


def test_wrapper_unsandbox_initialize_and_hello(
    tmp_path,
    pick_free_port,
    mcp_stdio_protocol,
    pkg_src_env_update,
    launch_proc,
):
    port = pick_free_port
    cmd = [
        sys.executable,
        "-m",
        "jupyter_mcp_stdio_guard",
        "--workspace",
        str(tmp_path / "ws"),
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
            timeout=20.0,
        )
        assert "hello world" in str(result)
