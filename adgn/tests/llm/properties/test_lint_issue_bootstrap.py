from __future__ import annotations

from pathlib import Path
import shutil
import uuid
from platformdirs import user_cache_dir

from adgn.llm.openai_utils.model import (
    FakeOpenAIModel,
)
from tests.fixtures.responses import ResponsesFactory
import pytest

from adgn.llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn.llm.mcp._shared.container_session import ContainerOptions
from adgn.llm.mcp._shared.types import ExecInput
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.properties.docker_env import PropertiesDockerWiring
from adgn.llm.properties.lint_issue import LinterController, LintSubmitState
from adgn.llm.properties.models.issue import Occurrence


def _make_seq() -> list:
    rf = ResponsesFactory("gpt-5-nano")
    return [
        rf.make(
            rf.tool_call(
                "mcp__docker__docker_exec",
                ExecInput(cmd=["bash", "-lc", "echo from_llm"]).model_dump(),
            )
        ),
        rf.make_assistant_message("FINAL"),
    ]


@pytest.fixture
def content_root() -> Path:
    """Workspace under XDG cache (Colima-compatible bind mount). Cleans up after test."""
    cache_root = Path(user_cache_dir("adgn-tests")) / "workspaces"
    cache_root.mkdir(parents=True, exist_ok=True)
    p = cache_root / f"repo-{uuid.uuid4().hex[:8]}"
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


@pytest.mark.asyncio
@pytest.mark.requires_docker
async def test_lint_issue_bootstrap_small_files(content_root: Path):
    # Arrange: create a tiny workspace with two small files
    # Colima note: bind mounts from /tmp are blocked; place workspace under XDG cache dir.
    content_root.mkdir(parents=True, exist_ok=True)
    (content_root / "pkg").mkdir(parents=True, exist_ok=True)
    f1 = content_root / "pkg" / "a.py"
    f2 = content_root / "pkg" / "b.py"
    f1.write_text("print('a')\n", encoding="utf-8")
    f2.write_text("print('b')\n", encoding="utf-8")

    # Occurrence: two files, no explicit ranges (whole-file path)
    occ = Occurrence(files={"pkg/a.py": None, "pkg/b.py": None})

    # Bootstrap controller (3-turn plan)
    # We'll create the PropertiesDockerWiring after we build the inproc spec below and assign it directly.

    # Real MCP manager (in-proc docker exec) and mocked OpenAI client
    spec = make_inproc_slot_spec(
        make_container_exec_mcp(
            ContainerOptions(
                image="python:3.12-slim",
                working_dir="/workspace",
                volumes={str(content_root): {"bind": "/workspace", "mode": "ro"}},
                describe=False,
            )
        ),
    )
    # Use our shared Pydantic-only fake OpenAI client with canned outputs
    client = FakeOpenAIModel(_make_seq())

    # Now create the controller with real wiring
    wiring = PropertiesDockerWiring(
        server_spec=spec,
        working_dir=Path("/workspace"),
        definitions_container_dir=None,
        image_name="n/a",
    )
    ctrl = LinterController(
        state=LintSubmitState(),
        occ=occ,
        content_root=content_root,
        docker_wiring=wiring,
    )

    async with McpManager({"docker": spec}) as mcp:
        agent = await MiniCodex.create(
            model="gpt-5",
            mcp=mcp,
            system="test",
            client=client,
            handlers=[ctrl, DisplayEventsHandler()],
        )

        # Act
        res = await agent.run(user_text="bootstrap lint")

    # Assert final text
    assert res.text.strip() == "FINAL"

    # Inspect transcript for bootstrap then LLM tool call then final text
    messages = agent.messages
    # Function call outputs we expect: resources.read (bootstrap:res), ls (bootstrap:ls), nl for each file (bootstrap:show:*)
    from adgn.llm.openai_utils.model import (
        FunctionCallOutputItem,
        AssistantMessage,
        InputTextPart,
    )

    fco = [m for m in messages if isinstance(m, FunctionCallOutputItem)]
    by_id = {m.call_id: m for m in fco}
    # At least 3 bootstrap outputs + 1 LLM tool output
    assert len(fco) >= 4

    # Verify expected bootstrap call_ids are present; transcript may not embed structuredContent here
    assert by_id.get("bootstrap:res") is not None
    assert by_id.get("bootstrap:ls") is not None
    show_ids = [
        k for k in by_id if isinstance(k, str) and k.startswith("bootstrap:show:")
    ]
    assert len(show_ids) >= 2

    # Ensure we saw a final assistant emission with text "FINAL"
    def _is_final(msg) -> bool:
        # assistant message content is a list of InputTextPart blocks in our typed interface
        if isinstance(msg, AssistantMessage):
            for block in msg.content or []:
                if isinstance(block, InputTextPart) and block.text.strip() == "FINAL":
                    return True
        return False

    assert any(_is_final(m) for m in messages)

    # Cleanup workspace to avoid clutter under $HOME
    try:
        shutil.rmtree(content_root, ignore_errors=True)
    except Exception:
        pass
