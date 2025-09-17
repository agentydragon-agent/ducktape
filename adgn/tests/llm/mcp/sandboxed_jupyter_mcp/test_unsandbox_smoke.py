def test_unsandbox_initialize_and_hello(  # noqa: PLR0913
    tmp_path,
    pick_free_port,
    gen_token,
    wait_port,
    mcp_stdio_protocol,
    launch_proc,
    launch_jupyter_server,
):
    port = pick_free_port
    token = gen_token

    with launch_jupyter_server(port, token) as (_ws, nb_rel):
        assert wait_port(port, 15.0), "Jupyter server did not start"

        mcp_cmd = [
            "jupyter-mcp-server",
            "start",
            "--transport",
            "stdio",
            "--provider",
            "jupyter",
            "--document-url",
            f"http://127.0.0.1:{port}",
            "--document-id",
            str(nb_rel),
            "--document-token",
            token,
            "--runtime-url",
            f"http://127.0.0.1:{port}",
            "--runtime-token",
            token,
            "--start-new-runtime",
            "true",
        ]

        with launch_proc(mcp_cmd) as proc:
            result = mcp_stdio_protocol(
                proc.stdin,
                proc.stdout,
                "append_execute_code_cell",
                {"cell_source": "print('hello world')"},
                timeout=20.0,
            )
            assert "hello world" in str(result)
