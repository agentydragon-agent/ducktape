"""Unmodified 2.1.296 with scripted loopback model and SDK MCP peers.

Forwarding switches are startup inputs, not simulated account entitlement.
No feature cache, embedded source, OAuth identity, or native permission gate is patched.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_bazel
from aiohttp import web
from fastmcp import FastMCP

from agentplane.native.claude import scenarios, wire
from agentplane.native.claude.testing import anthropic_sse
from agentplane.native.claude.testing.async_run import ClaudeRun
from agentplane.native.claude.testing.mcp import DriverMcpServer
from agentplane.native.claude.testing.messages import AnthropicMessages
from agentplane.native.claude.testing.model import MODEL
from agentplane.native.claude.testing.requests import MessagesRequest
from util.bazel.runfiles import get_required_path
from util.testing.undeclared_outputs import undeclared_outputs_dir

ROOT = "ROOT_INSTRUCTION_7b32c8"
NESTED = "NESTED_INSTRUCTION_5d61a4"
SIBLING = "SIBLING_INSTRUCTION_943fc1"


def _capture(name: str, request: MessagesRequest) -> str:
    text = request.model_dump_json(indent=2)
    (undeclared_outputs_dir() / f"{name}.json").write_text(text)
    return text


@asynccontextmanager
async def _bridge_probe() -> AsyncIterator[tuple[str, list[str]]]:
    """A loopback HTTP/WS destination that records every attempted handshake."""
    paths: list[str] = []

    async def reject(request: web.Request) -> web.Response:
        paths.append(f"{request.method} {request.path_qs}")
        return web.Response(status=403)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", reject)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    (address,) = runner.addresses
    try:
        yield f"http://127.0.0.1:{address[1]}", paths
    finally:
        await runner.cleanup()


@asynccontextmanager
async def _run(
    workspace: Path,
    logs: Path,
    environment: dict[str, str],
    config: Path,
    endpoint: AnthropicMessages,
    *,
    resume_id: str | None = None,
    forward: bool = False,
    bridge: str | None = None,
    mcp: DriverMcpServer | None = None,
    deny_tools: bool = False,
) -> AsyncIterator[ClaudeRun]:
    await asyncio.to_thread(config.mkdir, exist_ok=True)
    await asyncio.to_thread(logs.mkdir, parents=True, exist_ok=True)
    command = scenarios.command(
        str(get_required_path("claude_remote_tools_cli_linux_x64/claude")),
        model=MODEL,
        session_name="remote-tools-characterization",
        tools=("Read", "Edit"),
        permission_mode="manual",
        resume_id=resume_id,
        # Ordinary instruction loading; hook callbacks permit explicit denial experiments.
        hooks=True,
    )
    # Enable the project source so the fixture CLAUDE.md is loaded.
    command[command.index("--setting-sources=")] = "--setting-sources=project"
    debug_file = config / f"debug-{logs.name}.log"
    command.extend(["--debug-file", str(debug_file)])
    responder = scenarios.hook_answers(deny_tools=deny_tools)

    async def respond(frame: dict[str, Any]) -> wire.ControlResponse | None:
        if mcp is not None:
            reply = await mcp.respond(frame)
            if reply is not None:
                return reply
        return await responder(frame)

    env = {
        **environment,
        **scenarios.environment(endpoint=endpoint.origin, token="test-key", config_dir=str(config), max_retries=0),
        "CLAUDE_CODE_REMOTE_TOOLS_FORWARD": "1" if forward else "0",
        "CLAUDE_CODE_REMOTE_TOOLS_SESSION_CHANNEL": "0",
        # Unexpected external traffic fails against this loopback rejecting destination.
        "HTTP_PROXY": bridge or "http://127.0.0.1:9",
        "HTTPS_PROXY": bridge or "http://127.0.0.1:9",
    }
    if bridge is not None:
        env["CLAUDE_REMOTE_TOOLS_BRIDGE_URL"] = bridge.replace("http:", "ws:")
    async with ClaudeRun(
        logs,
        command,
        cwd=workspace,
        environment=env,
        responder=respond,
        hooks=True,
        sdk_mcp_servers=[mcp.name] if mcp is not None else None,
    ) as run:
        try:
            yield run
        finally:
            # The CLI also creates an absolute `latest` symlink beside its debug file.
            # Publish only the real file; the temp-directory link is not a Bazel output.
            if debug_file.exists():
                (logs / "debug.log").write_text(debug_file.read_text())


def _instructions(workspace: Path) -> Path:
    (workspace / "CLAUDE.md").write_text(f"Project instruction: {ROOT}\n")
    nested = workspace / "nested"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text(f"Nested instruction: {NESTED}\n")
    sibling = workspace / "sibling"
    sibling.mkdir()
    (sibling / "CLAUDE.md").write_text(f"Sibling instruction: {SIBLING}\n")
    target = nested / "editable.txt"
    target.write_text("before\n")
    return target


@pytest.mark.parametrize("forward", [False, True])
async def test_native_instruction_loading_and_forwarding_startup(
    workspace: Path,
    native_logs: Path,
    base_environment: dict[str, str],
    tmp_path: Path,
    anthropic_messages: AnthropicMessages,
    forward: bool,
) -> None:
    target = _instructions(workspace)
    prefix = f"native-forward-{forward}"
    async with asyncio.timeout(35), _bridge_probe() as (bridge, requests):
        async with _run(
            workspace,
            native_logs,
            base_environment,
            tmp_path / "config",
            anthropic_messages,
            forward=forward,
            bridge=bridge,
        ) as run:
            prompt = await run.send("Read the nested editable file.")
            async with await anthropic_messages.await_next_request() as exchange:
                first = _capture(f"{prefix}-before-read", exchange.request)
                assert first.count(ROOT) == 1
                assert NESTED not in first
                assert SIBLING not in first
                assert "Read" in exchange.request.tool_names
                await exchange.send(
                    *anthropic_sse.message_stream(
                        [anthropic_sse.ToolUse("native_read", "Read", {"file_path": str(target)})], model=MODEL
                    ).events
                )
            async with await anthropic_messages.await_next_request() as exchange:
                after = _capture(f"{prefix}-after-read", exchange.request)
                assert "before" in exchange.request.tool_results[0].text
                assert after.count(ROOT) == 1
                assert after.count(NESTED) == 1
                assert SIBLING not in after
                await exchange.send(*anthropic_sse.message_stream([anthropic_sse.Text("DONE")], model=MODEL).events)
            assert (await prompt.result()).result == "DONE"
        (undeclared_outputs_dir() / f"{prefix}-bridge.json").write_text(json.dumps(requests, indent=2))
        # This synthetic account/provider setup does not establish bridge eligibility.
        assert requests == []


async def test_driver_mcp_read_does_not_load_native_nested_instructions(
    workspace: Path,
    native_logs: Path,
    base_environment: dict[str, str],
    tmp_path: Path,
    anthropic_messages: AnthropicMessages,
) -> None:
    target = _instructions(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE_DATA_0a947d\n")
    (workspace / "escape.txt").symlink_to(outside)
    server = FastMCP("fixture")

    @server.tool
    def read_file(path: str) -> str:
        """Read a file within the fixture workspace."""
        resolved = (workspace / path).resolve()
        if not resolved.is_relative_to(workspace):
            raise ValueError("outside fixture workspace")
        return resolved.read_text()

    async with (
        asyncio.timeout(35),
        _run(
            workspace,
            native_logs,
            base_environment,
            tmp_path / "config",
            anthropic_messages,
            mcp=DriverMcpServer("fixture", server),
        ) as run,
    ):
        prompt = await run.send("Read the nested file with the fixture tool.")
        async with await anthropic_messages.await_next_request() as exchange:
            _capture("mcp-before-read", exchange.request)
            assert "mcp__fixture__read_file" in exchange.request.tool_names
            await exchange.send(
                *anthropic_sse.message_stream(
                    [
                        anthropic_sse.ToolUse(
                            "mcp_read", "mcp__fixture__read_file", {"path": str(target.relative_to(workspace))}
                        )
                    ],
                    model=MODEL,
                ).events
            )
        async with await anthropic_messages.await_next_request() as exchange:
            after = _capture("mcp-after-read", exchange.request)
            assert exchange.request.tool_results[0].is_error is False
            assert "before" in exchange.request.tool_results[0].text
            assert after.count(ROOT) == 1
            assert NESTED not in after
            assert SIBLING not in after
            await exchange.send(
                *anthropic_sse.message_stream(
                    [
                        anthropic_sse.ToolUse(
                            "edit_after_mcp_read",
                            "Edit",
                            {"file_path": str(target), "old_string": "before", "new_string": "after"},
                        )
                    ],
                    model=MODEL,
                ).events
            )
        async with await anthropic_messages.await_next_request() as exchange:
            _capture("mcp-read-native-edit", exchange.request)
            assert exchange.request.tool_results[0].is_error is True
            assert target.read_text() == "before\n"
            await exchange.send(
                *anthropic_sse.message_stream(
                    [
                        anthropic_sse.ToolUse("mcp_outside", "mcp__fixture__read_file", {"path": "../outside.txt"}),
                        anthropic_sse.ToolUse("mcp_symlink", "mcp__fixture__read_file", {"path": "escape.txt"}),
                    ],
                    model=MODEL,
                ).events
            )
        async with await anthropic_messages.await_next_request() as exchange:
            text = _capture("mcp-outside-denial", exchange.request)
            assert len(exchange.request.tool_results) == 2
            for result in exchange.request.tool_results:
                assert result.is_error is True
                assert "outside fixture workspace" in result.text
            assert "OUTSIDE_DATA_0a947d" not in text
            assert outside.read_text() == "OUTSIDE_DATA_0a947d\n"
            await exchange.send(*anthropic_sse.message_stream([anthropic_sse.Text("DONE")], model=MODEL).events)
        assert (await prompt.result()).result == "DONE"


async def test_native_read_edit_state_across_resume_and_independent_session(
    workspace: Path,
    native_logs: Path,
    base_environment: dict[str, str],
    tmp_path: Path,
    anthropic_messages: AnthropicMessages,
) -> None:
    target = workspace / "editable.txt"
    target.write_text("before\n")
    config = tmp_path / "config"
    async with asyncio.timeout(50):
        async with _run(workspace, native_logs / "initial", base_environment, config, anthropic_messages) as run:
            prompt = await run.send("Exercise read-before-edit state.")
            async with await anthropic_messages.await_next_request() as exchange:
                await exchange.send(
                    *anthropic_sse.message_stream(
                        [
                            anthropic_sse.ToolUse(
                                "unread_edit",
                                "Edit",
                                {"file_path": str(target), "old_string": "before", "new_string": "after"},
                            )
                        ],
                        model=MODEL,
                    ).events
                )
            async with await anthropic_messages.await_next_request() as exchange:
                _capture("state-unread-edit", exchange.request)
                assert exchange.request.tool_results[0].is_error is True
                assert target.read_text() == "before\n"
                await exchange.send(
                    *anthropic_sse.message_stream(
                        [anthropic_sse.ToolUse("state_read", "Read", {"file_path": str(target)})], model=MODEL
                    ).events
                )
            async with await anthropic_messages.await_next_request() as exchange:
                assert exchange.request.tool_results[0].is_error is False
                await exchange.send(
                    *anthropic_sse.message_stream(
                        [
                            anthropic_sse.ToolUse(
                                "read_edit",
                                "Edit",
                                {"file_path": str(target), "old_string": "before", "new_string": "after"},
                            )
                        ],
                        model=MODEL,
                    ).events
                )
            async with await anthropic_messages.await_next_request() as exchange:
                _capture("state-read-edit", exchange.request)
                assert exchange.request.tool_results[0].is_error is False
                assert target.read_text() == "after\n"
                await exchange.send(*anthropic_sse.message_stream([anthropic_sse.Text("SEEDED")], model=MODEL).events)
            result = await prompt.result()
        outcomes = {}
        for name, resume_id in (("resume", result.session_id), ("independent", None)):
            async with _run(
                workspace, native_logs / name, base_environment, config, anthropic_messages, resume_id=resume_id
            ) as run:
                prompt = await run.send("Attempt an edit without a new Read call.")
                old = target.read_text().strip()
                async with await anthropic_messages.await_next_request() as exchange:
                    await exchange.send(
                        *anthropic_sse.message_stream(
                            [
                                anthropic_sse.ToolUse(
                                    f"{name}_edit",
                                    "Edit",
                                    {"file_path": str(target), "old_string": old, "new_string": name},
                                )
                            ],
                            model=MODEL,
                        ).events
                    )
                async with await anthropic_messages.await_next_request() as exchange:
                    _capture(f"state-{name}-edit", exchange.request)
                    outcomes[name] = {"is_error": exchange.request.tool_results[0].is_error, "file": target.read_text()}
                    await exchange.send(*anthropic_sse.message_stream([anthropic_sse.Text("DONE")], model=MODEL).events)
                assert (await prompt.result()).result == "DONE"
        (undeclared_outputs_dir() / "state-outcomes.json").write_text(json.dumps(outcomes, indent=2))
        assert outcomes["resume"]["is_error"] is False
        assert outcomes["resume"]["file"] == "resume\n"
        assert outcomes["independent"]["is_error"] is True
        assert outcomes["independent"]["file"] == "resume\n"


@pytest.mark.parametrize("tool", ["Read", "mcp__fixture__read_file"])
async def test_explicit_hook_denial_prevents_file_access(
    workspace: Path,
    native_logs: Path,
    base_environment: dict[str, str],
    tmp_path: Path,
    anthropic_messages: AnthropicMessages,
    tool: str,
) -> None:
    target = _instructions(workspace)
    target.write_text("DENIED_CONTENT_a31ef9\n")
    calls: list[str] = []
    server = FastMCP("fixture")

    @server.tool
    def read_file(path: str) -> str:
        """Read the fixture file."""
        calls.append(path)
        return target.read_text()

    async with (
        asyncio.timeout(35),
        _run(
            workspace,
            native_logs,
            base_environment,
            tmp_path / "config",
            anthropic_messages,
            mcp=DriverMcpServer("fixture", server),
            deny_tools=True,
        ) as run,
    ):
        prompt = await run.send("Attempt the denied read.")
        async with await anthropic_messages.await_next_request() as exchange:
            arguments = {"file_path": str(target)} if tool == "Read" else {"path": str(target)}
            await exchange.send(
                *anthropic_sse.message_stream(
                    [anthropic_sse.ToolUse("denied_read", tool, arguments)], model=MODEL
                ).events
            )
        async with await anthropic_messages.await_next_request() as exchange:
            text = _capture(f"denial-{tool}", exchange.request)
            assert exchange.request.tool_results[0].is_error is True
            assert scenarios.HOOK_DENIAL in exchange.request.tool_results[0].text
            assert NESTED not in text
            assert "DENIED_CONTENT_a31ef9" not in text
            assert calls == []
            await exchange.send(*anthropic_sse.message_stream([anthropic_sse.Text("DENIED")], model=MODEL).events)
        assert (await prompt.result()).result == "DENIED"


if __name__ == "__main__":
    pytest_bazel.main()
