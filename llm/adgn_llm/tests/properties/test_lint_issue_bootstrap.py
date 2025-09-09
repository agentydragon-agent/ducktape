from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.inproc_utils import make_inproc_slot_spec
from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.properties.lint_issue import _make_bootstrap_controller
from adgn_llm.properties.specimen_utils import Occurrence, LineRange


class _MockResponsesClient:
    def __init__(self):
        self._calls = 0

    class _Sub:
        def __init__(self, parent: "_MockResponsesClient"):
            self._p = parent

        async def create(self, **kwargs):  # noqa: D401
            # 1st real LLM call: request a docker_exec tool
            self._p._calls += 1
            if self._p._calls == 1:
                return type(
                    "Resp",
                    (),
                    {
                        "output": [
                            ResponseFunctionToolCall(
                                type="function_call",
                                name="mcp__docker__docker_exec",
                                call_id="llm:1",
                                arguments=json.dumps({"cmd": ["bash", "-lc", "echo from_llm"]}),
                            )
                        ]
                    },
                )()
            # 2nd real LLM call: return final assistant text
            return type(
                "Resp",
                (),
                {
                    "output": [
                        ResponseOutputMessage(
                            id="out-msg-1",
                            type="message",
                            role="assistant",
                            status="completed",
                            content=[
                                ResponseOutputText(type="output_text", text="FINAL", annotations=[])
                            ],
                        )
                    ]
                },
            )()

    @property
    def responses(self) -> "_MockResponsesClient._Sub":  # noqa: D401
        return _MockResponsesClient._Sub(self)


@pytest.mark.asyncio
async def test_lint_issue_bootstrap_small_files(tmp_path: Path):
    # Arrange: create a tiny workspace with two small files
    # Use a repo under the project working directory to satisfy Docker Desktop file sharing
    import os, time
    content_root = Path.cwd() / "scratch" / f"bootstrap_repo_{os.getpid()}_{int(time.time())}"
    content_root.mkdir(parents=True, exist_ok=False)
    (content_root / "pkg").mkdir(parents=True)
    f1 = content_root / "pkg" / "a.py"
    f2 = content_root / "pkg" / "b.py"
    f1.write_text("print('a')\n", encoding="utf-8")
    f2.write_text("print('b')\n", encoding="utf-8")

    # Occurrence: two files, no explicit ranges (whole-file path)
    occ = Occurrence(files={"pkg/a.py": None, "pkg/b.py": None})

    # Bootstrap controller (3-turn plan)
    ctrl = _make_bootstrap_controller(occ, content_root)

    # Real MCP manager (in-proc docker exec) and mocked OpenAI client
    spec = make_inproc_slot_spec(
        make_container_exec_mcp(
            image="python:3.12-slim",
            working_dir="/workspace",
            volumes={str(content_root): {"bind": "/workspace", "mode": "ro"}},
            describe=False,
        )
    )
    mcp = McpManager({"docker": spec})
    client = _MockResponsesClient()

    agent = await MiniCodex.create(model="gpt-5", mcp=mcp, system="test", client=client)

    # Act
    res = await agent.run(user_text="bootstrap lint", controller=ctrl)

    # Assert final text
    assert res.text.strip() == "FINAL"

    # Inspect transcript for bootstrap then LLM tool call then final text
    messages = agent.messages
    # Count function_call_output blocks (container.info, ls, cat a.py, cat b.py, and the LLM-triggered docker call)
    fco = [m for m in messages if m.get("type") == "function_call_output"]
    # At least 3 bootstrap outputs + 1 LLM tool output
    assert len(fco) >= 4
    # Ensure the last assistant message is our FINAL text
    assert any(m.get("role") == "assistant" and m.get("content") == "FINAL" for m in messages)
