"""
Demo: Run mini-codex against a real MCP stdio server (docker_exec) to act inside a
fresh tiny Docker container, using the real OpenAI API.

Prereqs:
- OPENAI_API_KEY set
- Docker daemon available (local)
- Python docker SDK installed (already a dependency of this project)

What it does:
1) Starts an alpine:3.19 container that sleeps
2) Launches the docker_exec MCP server via stdio (as a Python process) bound to that container
3) Invokes mini-codex (in-process) with only the docker_exec tool available
4) Asks the agent to create /tmp/ok.txt with 'hello' and print it
5) Verifies via Docker API that the file exists and contains 'hello' and cleans up
"""

from __future__ import annotations

import asyncio
import os
import time

import docker
from mcp.client.stdio import StdioServerParameters, stdio_client

from adgn_llm.mini_codex.cli import (
    AssistantMessage,
    FunctionCallOutput,
    UserMessage,
    openai_client,
    responses_followup_with_tool_outputs,
    responses_turn,
)
from adgn_llm.mini_codex.mcp_manager import McpManager, ServerSlot, session_opener

CONSOLE_SCRIPT = "adgn-mcp-docker-exec"


async def run_demo() -> None:
    # 1) Start tiny container (alpine)
    dclient = docker.from_env()
    image = "alpine:3.19"
    try:
        dclient.images.pull(image)
    except Exception:
        # Ignore pull failures if image already local
        pass
    container = dclient.containers.run(
        image,
        name=f"minicodex-demo-{int(time.time())}",
        command=["sh", "-lc", "while :; do sleep 3600; done"],
        detach=True,
        tty=False,
    )

    try:
        # 2) Build MCP servers mapping for stdio
        os.environ["DOCKER_CONTAINER"] = container.id
        os.environ["USE_CONTAINER_TIMEOUT_WRAPPER"] = "0"
        servers = {
            "docker": {
                "command": CONSOLE_SCRIPT,
                "args": [],
                "env": {
                    "DOCKER_CONTAINER": container.id,
                    "USE_CONTAINER_TIMEOUT_WRAPPER": "0",
                },
            },
        }

        # 3) Create MCP manager (no local execution servers) using ServerSlotSpec
        client = openai_client()

        async with McpManager(McpManager.slots_from_specs({"docker": servers["docker"]})) as mcp:
            # Find the tool name the model will call (e.g., mcp__docker__docker_exec)
            tool_names = [t.get("name") for t in (await mcp.list_tools()) if t.get("type") == "function"]
            docker_tool = next(
                (n for n in tool_names if n and n.startswith("mcp__docker__")),
                None,
            )
            if not docker_tool:
                raise RuntimeError("docker MCP tool not found in manager")

            # 4) Build a short prompt instructing how to use the tool
            user_task = (
                f"Use the tool {docker_tool} to:\n"
                "1) create /tmp/ok.txt with the content 'hello' (exact lowercase)\n"
                "2) print the content of /tmp/ok.txt\n"
                "Reply briefly."
            )

            # Use mini_codex agent helpers to drive the loop with tool outputs
            transcript: list[UserMessage | AssistantMessage | FunctionCallOutput] = [
                UserMessage(role="user", content=user_task),
            ]
            terminal_batch: list[str] = []
            pending_tool_outputs: list[FunctionCallOutput] | None = None
            for _ in range(8):
                if pending_tool_outputs:
                    (
                        new_msgs,
                        terminal_text,
                    ) = await responses_followup_with_tool_outputs(
                        client,
                        transcript,
                        pending_tool_outputs,
                        mcp,
                    )
                    pending_tool_outputs = None
                else:
                    new_msgs, terminal_text = await responses_turn(client, transcript, mcp)
                if terminal_text:
                    terminal_batch.append(terminal_text)
                # Extend transcript with assistant messages only; tool outputs are sent explicitly next round
                transcript.extend([m for m in new_msgs if isinstance(m, AssistantMessage)])
                collected = [m for m in new_msgs if isinstance(m, FunctionCallOutput)]
                if collected:
                    pending_tool_outputs = collected
                else:
                    break
            if terminal_batch:
                print("Agent said:\n" + "\n".join(terminal_batch))

        # 5) Verify via Docker API that the file was created with correct contents
        exec_res = container.exec_run(
            ["sh", "-lc", "cat /tmp/ok.txt 2>/dev/null || echo MISSING"],
            stdout=True,
            stderr=True,
        )
        out = (
            exec_res.output.decode(errors="replace")
            if hasattr(exec_res, "output")
            else exec_res[1].decode(errors="replace")
        )
        got = out.strip()
        assert got == "hello", f"Verification failed: expected 'hello', got {got!r}"
        print("Verification: OK (hello)")

    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_demo())
