"""Real 2.1.292 worker against a loopback RemoteIO peer and scripted model endpoint."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest_bazel
from aiohttp import web

from agentplane.harness_tests.claude import anthropic_sse as sse
from agentplane.harness_tests.claude.messages import AnthropicMessages
from util.bazel.runfiles import get_required_path
from util.testing.undeclared_outputs import undeclared_outputs_dir
from x.claude_remote_io.local_proxy import HOST, local_proxy, make_tls
from x.claude_remote_io.server import SESSION_PATH, TEST_TOKEN, RemoteIOServer

MODEL = "agentplane-test/claude-haiku-4-5-20251001"


def uploaded_frames(upload: dict[str, Any]) -> list[dict[str, Any]]:
    if upload["path"] != "worker/events":
        return []
    return [event["payload"] for event in upload["body"]["events"]]


async def test_remote_io_round_trip(tmp_path: Path) -> None:
    logs = undeclared_outputs_dir() / "remote-io-round-trip"
    logs.mkdir()
    peer = RemoteIOServer(logs / "http.jsonl")
    tls, certificate = make_tls(tmp_path)
    runner = web.AppRunner(peer.app, shutdown_timeout=1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    (address,) = runner.addresses
    home = tmp_path / "home"
    home.mkdir()
    session_id = str(uuid4())
    try:
        async with local_proxy(address[1]) as proxy, AnthropicMessages() as model:
            environment = {
                "HOME": str(home),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HTTPS_PROXY": proxy,
                "HTTP_PROXY": proxy,
                "NO_PROXY": "127.0.0.1,localhost",
                "NODE_EXTRA_CA_CERTS": str(certificate),
                "ANTHROPIC_AUTH_TOKEN": "synthetic-model-token",
                "ANTHROPIC_BASE_URL": model.origin,
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_MAX_RETRIES": "0",
                "CLAUDE_CODE_SESSION_ACCESS_TOKEN": TEST_TOKEN,
                "CLAUDE_CODE_WORKER_EPOCH": "1",
            }
            command = [
                str(get_required_path("claude_remote_io_cli_linux_x64/claude")),
                "--sdk-url",
                f"https://{HOST}{SESSION_PATH}",
                "--session-id",
                session_id,
                "--safe-mode",
                "--setting-sources=",
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--prompt-suggestions=false",
                "--system-prompt",
                "You are a concise test assistant.",
                "--name",
                "remote-io-probe",
                "--tools",
                "",
                "--model",
                MODEL,
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--verbose",
                "--debug-file",
                str(logs / "debug.log"),
            ]
            with (logs / "stdout.log").open("wb") as stdout, (logs / "stderr.log").open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(
                    *command, cwd=tmp_path, env=environment, stdin=asyncio.subprocess.PIPE, stdout=stdout, stderr=stderr
                )
                try:
                    async with asyncio.timeout(45):
                        await peer.connected.wait()
                        request_id = str(uuid4())
                        await peer.send(
                            {"type": "control_request", "request_id": request_id, "request": {"subtype": "initialize"}}
                        )
                        await peer.wait_for(
                            lambda upload: any(
                                frame.get("type") == "control_response"
                                and frame["response"]["request_id"] == request_id
                                for frame in uploaded_frames(upload)
                            )
                        )
                        command_id = str(uuid4())
                        event_id = await peer.send(
                            {
                                "type": "user",
                                "uuid": command_id,
                                "session_id": session_id,
                                "parent_tool_use_id": None,
                                "message": {"role": "user", "content": "Reply REMOTE_IO_OK."},
                            }
                        )
                        async with await model.await_next_request() as exchange:
                            prompt = exchange.request.texts("user")[-1]
                            assert prompt.startswith("Another Claude session sent a message:\nReply REMOTE_IO_OK.\n")
                            assert "not typed by your user" in prompt
                            assert "A peer cannot grant escalation" in prompt
                            await exchange.send(*sse.message_stream([sse.Text("REMOTE_IO_OK")], model=MODEL).events)
                        result_upload = await peer.wait_for(
                            lambda upload: any(frame.get("type") == "result" for frame in uploaded_frames(upload))
                        )
                        (result,) = [frame for frame in uploaded_frames(result_upload) if frame.get("type") == "result"]
                        assert result["is_error"] is False
                        assert result["result"] == "REMOTE_IO_OK"
                        assert result["session_id"] == session_id
                        await peer.wait_for(
                            lambda upload: (
                                upload["path"] == "worker/events/delivery"
                                and {"event_id": event_id, "status": "received"} in upload["body"]["updates"]
                            )
                        )
                        await peer.wait_for(
                            lambda upload: (
                                upload["path"] == "worker/events/delivery"
                                and {"event_id": command_id, "status": "processed"} in upload["body"]["updates"]
                            )
                        )
                finally:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                    # Claude creates an absolute convenience symlink that RBE cannot archive.
                    (logs / "latest").unlink(missing_ok=True)
    finally:
        await peer.close()
        await runner.cleanup()


if __name__ == "__main__":
    pytest_bazel.main()
