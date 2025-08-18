import subprocess
import pytest


def test_unsandbox_initialize_and_hello(
    tmp_path,
    pick_free_port,
    gen_token,
    wait_port,
    mcp_stdio_protocol,
    launch_proc,
):
    port = pick_free_port
    token = gen_token

    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    nb_rel = ws / ".mcp/test.ipynb"
    nb_rel.parent.mkdir(parents=True, exist_ok=True)
    nb_rel.write_text(
        '{"cells": [], "metadata": {"kernelspec": {"name":"python3","display_name":"Python 3","language":"python"}}, "nbformat":4, "nbformat_minor":5}'
    )

    js_cmd = [
        "jupyter",
        "server",
        "--port",
        str(port),
        "--ip",
        "127.0.0.1",
        "--ServerApp.root_dir",
        str(ws),
        "--ServerApp.open_browser",
        "False",
        "--ServerApp.token",
        token,
        "--ServerApp.password",
        "",
        "--ServerApp.disable_check_xsrf",
        "True",
    ]
    js_out = (ws / "jupyter_server.out").open("wb")
    js_err = (ws / "jupyter_server.err").open("wb")

    with subprocess.Popen(js_cmd, stdout=js_out, stderr=js_err) as js:
        try:
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
                str(nb_rel.relative_to(ws)),
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
        finally:
            js.terminate()
            js.kill()
            js_out.close()
            js_err.close()
