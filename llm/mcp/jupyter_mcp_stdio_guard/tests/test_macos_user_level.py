import sys


def test_user_view_end_to_end(
    tmp_path,
    pick_free_port,
    mcp_stdio_protocol,
    collect_mcp_logs_fn,
    pkg_src_env_update,
    launch_proc,
    require_macos_rtc,
):
    if sys.platform != "darwin":
        return
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
        "--trace-sandbox",
    ]
    try:
        with launch_proc(cmd, env_update=pkg_src_env_update) as proc:
            result = mcp_stdio_protocol(
                proc.stdin,
                proc.stdout,
                "append_execute_code_cell",
                {"cell_source": "print('hello world')"},
                timeout=20.0,
            )
            assert "hello world" in str(result)
    except AssertionError as e:
        out, err = collect_mcp_logs_fn()
        raise AssertionError(
            f"MCP protocol failed. Logs:\nstdout:\n{out}\nstderr:\n{err}\nError: {e}"
        )
