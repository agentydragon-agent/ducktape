from __future__ import annotations

from collections.abc import Generator
import contextlib
from pathlib import Path
import shutil
import uuid

from platformdirs import user_cache_dir
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.exec.docker.server import make_container_exec_server
from adgn.mcp.exec.models import ExecInput
from adgn.openai_utils.model import AssistantMessage, FunctionCallOutputItem, InputTextPart
from adgn.props.docker_env import WORKING_DIR, PropertiesDockerWiring
from adgn.props.lint_issue import LintSubmitState, make_linter_handlers
from adgn.props.models.true_positive import Occurrence
from tests.conftest import make_container_opts
from tests.llm.support.openai_mock import make_mock
from tests.support.steps import AssistantMessage as StepAssistantMessage, MakeCall


@pytest.fixture
def lint_bootstrap_steps():
    """Create steps for linter handlers bootstrap test.

    NOTE: Uses typed ExecInput model for docker_exec arguments to ensure
    correct validation and serialization for the MCP runtime server.
    """
    return [
        MakeCall("docker", "docker_exec", ExecInput(cmd=["bash", "-lc", "echo from_llm"], timeout_ms=10_000)),
        StepAssistantMessage("FINAL"),
    ]


@pytest.fixture
def content_root() -> Generator[Path, None, None]:
    """Workspace under XDG cache (Colima-compatible bind mount). Cleans up after test."""
    cache_root = Path(user_cache_dir("adgn-tests")) / "workspaces"
    cache_root.mkdir(parents=True, exist_ok=True)
    p = cache_root / f"repo-{uuid.uuid4().hex[:8]}"
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


@pytest.mark.requires_docker
async def test_lint_issue_bootstrap_small_files(
    content_root: Path, make_pg_client, make_step_runner, lint_bootstrap_steps
):
    # Arrange: create a tiny workspace with two small files
    # Colima note: bind mounts from /tmp are blocked; place workspace under XDG cache dir.
    content_root.mkdir(parents=True, exist_ok=True)
    (content_root / "pkg").mkdir(parents=True, exist_ok=True)
    f1 = content_root / "pkg" / "a.py"
    f2 = content_root / "pkg" / "b.py"
    f1.write_text("print('a')\n", encoding="utf-8")
    f2.write_text("print('b')\n", encoding="utf-8")

    # Occurrence: two files, no explicit ranges (whole-file path)
    occ = Occurrence(files={Path("pkg/a.py"): None, Path("pkg/b.py"): None})

    # Real MCP manager (in-proc docker exec) and mocked OpenAI client
    opts = make_container_opts("python:3.12-slim")
    opts.volumes = {str(content_root): {"bind": "/workspace", "mode": "ro"}}
    opts.describe = False
    runtime_server = make_container_exec_server(opts)
    # Use our shared step runner with typed mock
    runner = make_step_runner(steps=lint_bootstrap_steps)
    client = make_mock(runner.handle_request_async)

    # Now create the handlers with real wiring
    wiring = PropertiesDockerWiring(
        server_factory=lambda: runtime_server, working_dir=WORKING_DIR, definitions_container_dir=None, image_name="n/a"
    )
    state = LintSubmitState()
    handlers = make_linter_handlers(state=state, occ=occ, content_root=content_root, docker_wiring=wiring)

    async with make_pg_client({"runtime": runtime_server}) as mcp_client:
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system="test",
            client=client,
            handlers=[*handlers, DisplayEventsHandler()],
            tool_policy=RequireAnyTool(),
        )

        # Act
        res = await agent.run(user_text="bootstrap lint")

    # Assert final text
    assert res.text.strip() == "FINAL"

    # Inspect transcript for bootstrap then LLM tool call then final text
    messages = agent.messages
    fco = [m for m in messages if isinstance(m, FunctionCallOutputItem)]

    # Verify we have bootstrap outputs and the LLM's tool call
    bootstrap_outputs = [m for m in fco if m.call_id.startswith("bootstrap:")]
    test_outputs = [m for m in fco if m.call_id.startswith("test:")]

    # Expect: container.info + ls + 2 file reads (nl) from bootstrap, plus 1 from test
    assert len(bootstrap_outputs) >= 4, f"Expected >=4 bootstrap outputs, got {len(bootstrap_outputs)}"
    assert len(test_outputs) >= 1, f"Expected >=1 test outputs, got {len(test_outputs)}"

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
    with contextlib.suppress(Exception):
        shutil.rmtree(content_root, ignore_errors=True)
