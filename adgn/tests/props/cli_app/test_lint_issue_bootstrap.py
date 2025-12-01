from __future__ import annotations

from collections.abc import Generator
import contextlib
from pathlib import Path
import shutil
import uuid

from platformdirs import user_cache_dir
import pytest

from adgn.agent.agent import MiniCodex
from adgn.agent.bootstrap import BootstrapHandler
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loop_control import Auto, Continue, NoLoopDecision
from adgn.agent.reducer import GateUntil
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.exec.docker.server import make_container_exec_server
from adgn.mcp.exec.models import ExecInput
from adgn.openai_utils.model import AssistantMessage, FunctionCallOutputItem, InputTextPart
from adgn.props.docker_env import WORKING_DIR, PropertiesDockerWiring
from adgn.props.lint_issue import LintSubmitState, make_linter_bootstrap_calls
from adgn.props.models.issue import Occurrence
from tests.conftest import make_container_opts
from tests.llm.support.openai_mock import FakeOpenAIModel
from tests.support.responses import ResponsesFactory


def _make_seq() -> list:
    responses_factory = ResponsesFactory("gpt-5-nano")
    return [
        responses_factory.make(
            responses_factory.tool_call(
                build_mcp_function("docker", "docker_exec"),
                ExecInput(cmd=["bash", "-lc", "echo from_llm"], timeout_ms=10_000).model_dump(),
            )
        ),
        responses_factory.make_assistant_message("FINAL"),
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
async def test_lint_issue_bootstrap_small_files(content_root: Path, make_pg_client):
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
    # Use our shared Pydantic-only fake OpenAI client with canned outputs
    client = FakeOpenAIModel(_make_seq())

    # Create wiring and bootstrap handlers
    wiring = PropertiesDockerWiring(
        server_factory=lambda: runtime_server, working_dir=WORKING_DIR, definitions_container_dir=None, image_name="n/a"
    )
    submit_state = LintSubmitState()
    bootstrap_calls = make_linter_bootstrap_calls(
        wiring=wiring, occ=occ, content_root=content_root, prop_host_paths=None
    )

    # Bootstrap handler with _done flag for deferral coordination
    class BootstrapWithDone(BootstrapHandler):
        def __init__(self, calls):
            super().__init__(calls)
            self._done = False

        def on_before_sample(self):
            if self._done:
                return NoLoopDecision()
            if not self._injected:
                self._injected = True
                return Continue(tool_policy=Auto(), inserts_input=tuple(self._calls), skip_sampling=True)
            # Second cycle: mark done
            self._done = True
            return NoLoopDecision()

    bootstrap_handler = BootstrapWithDone(bootstrap_calls)
    # GateUntil defers while bootstrap hasn't completed (matches critic.py pattern)
    gate_handler = GateUntil(
        is_done=lambda: submit_state.result is not None, defer_when=lambda: not bootstrap_handler._done
    )

    async with make_pg_client({"runtime": runtime_server}) as mcp_client:
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system="test",
            client=client,
            handlers=[bootstrap_handler, gate_handler, DisplayEventsHandler()],
        )

        # Act
        res = await agent.run(user_text="bootstrap lint")

    # Assert final text
    assert res.text.strip() == "FINAL"

    # Inspect transcript for bootstrap then LLM tool call then final text
    messages = agent.messages
    # Function call outputs we expect: resources.read (bootstrap:1), ls (bootstrap:2), nl for each file (bootstrap:3, bootstrap:4)
    fco = [m for m in messages if isinstance(m, FunctionCallOutputItem)]
    by_id = {m.call_id: m for m in fco}
    # At least 4 bootstrap outputs + 1 LLM tool output
    assert len(fco) >= 5

    # Verify expected bootstrap call_ids are present (auto-generated as bootstrap:N)
    bootstrap_ids = [k for k in by_id if isinstance(k, str) and k.startswith("bootstrap:")]
    # We expect: 1 container info + 1 ls + 2 nl (for two files) = 4 bootstrap calls
    assert len(bootstrap_ids) >= 4

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
