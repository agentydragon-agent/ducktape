def test_wrapper_unsandbox_initialize_and_hello(
    provision_ws_with_policy,
    pick_free_port,
    mcp_stdio_protocol,
    pkg_src_env_update,
    launch_proc,
):
    (ws, _run_root) = provision_ws_with_policy
    port = pick_free_port
    cmd = [
        "sandbox-jupyter-mcp",
        "--workspace",
        str(ws),
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
