from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
import shutil
import uuid

from fastmcp.client import Client
from platformdirs import user_cache_dir
from props_core.lint.lint_issue import LintIssueCompositor, LintSubmitState, make_linter_handlers
from props_core.models.true_positive import Occurrence
import pytest

from agent_core.agent import Agent
from agent_core.loop_control import RequireAnyTool
from agent_core.testing import AssistantMessage as StepAssistantMessage, DockerExecCall
from mcp_infra.display import DisplayEventsHandler
from openai_utils.model import AssistantMessage, FunctionCallOutputItem, InputTextPart, UserMessage


@pytest.fixture
def lint_bootstrap_steps():
    """Create steps for linter handlers bootstrap test."""
    return [DockerExecCall(["bash", "-lc", "echo from_llm"], tool_name="docker_exec"), StepAssistantMessage("FINAL")]


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


@pytest.mark.skip(
    reason="""TODO: Turn count expectation mismatch - needs update.
    Consider testing within agent e2e tests to include agent's database access testing.
    """
)
@pytest.mark.requires_docker
async def test_lint_issue_bootstrap_small_files(
    content_root: Path, make_step_runner, lint_bootstrap_steps, async_docker_client
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
    occ = Occurrence.from_files_dict(files={Path("pkg/a.py"): None, Path("pkg/b.py"): None})

    # Use step runner - implements OpenAIModelProto directly
    runner = make_step_runner(steps=lint_bootstrap_steps)

    # Create state using production pattern
    state = LintSubmitState()

    # Use LintIssueCompositor like production code does (no policy middleware needed)
    async with LintIssueCompositor(
        workspace_root=content_root, docker_client=async_docker_client, submit_state=state
    ) as comp:
        # Build handlers using compositor's mounted servers
        handlers = make_linter_handlers(
            state=state,
            resources=comp.resources,
            runtime=comp.runtime,
            occ=occ,
            content_root=content_root,
            compositor=comp,
        )

        # Create agent with Client connected to compositor
        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=runner,
                handlers=[*handlers, DisplayEventsHandler()],
                tool_policy=RequireAnyTool(),
            )

            # Act
            agent.process_message(UserMessage.text("bootstrap lint"))
            res = await agent.run()

    # Assert final text
    assert res.text.strip() == "FINAL"

    # Inspect transcript for bootstrap then LLM tool call then final text
    messages = agent.to_openai_messages()
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
