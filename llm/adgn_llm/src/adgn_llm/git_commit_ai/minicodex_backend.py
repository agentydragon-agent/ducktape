from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from git import Repo
import json

from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall
import logging
from adgn_llm.logging_config import configure_logging

from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mini_codex.loop_control import (
    Continue,
    Abort,
    RequireAny,
    SyntheticAction,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.properties.docker_env import properties_docker_spec
from adgn_llm.mcp.docker_exec.server import TOOL_EXEC_NAME as DOCKER_EXEC_TOOL_NAME


class CommitMessage(BaseModel):
    """Minimal commit message payload."""

    subject: str = Field(..., description="<=72 chars, imperative mood")
    body: str | None = Field(default=None, description="Optional body")


@dataclass
class SubmitState:
    result: CommitMessage | None = None


def make_submit_server(state: SubmitState):
    from mcp.server.fastmcp import FastMCP

    m = FastMCP(
        "submit_commit_message",
        instructions="Submit commit message (subject/body) and finish",
    )

    @m.tool()
    async def submit_commit_message(payload: CommitMessage) -> dict[str, bool]:
        state.result = payload
        return {"ok": True}

    return m


class CommitController(BaseHandler):
    """Emit bootstrap git calls in parallel on first turn; then require tools until submit."""

    def __init__(self, state: SubmitState, server_name: str) -> None:
        self._state = state
        self._server = server_name
        self._step = 0
        self._bootstrap = [
            ResponseFunctionToolCall(
                type="function_call",
                name=build_mcp_function(self._server, DOCKER_EXEC_TOOL_NAME),
                call_id="bootstrap:status",
                arguments=json.dumps(
                    {
                        "cmd": [
                            "git",
                            "-c",
                            "color.ui=false",
                            "-c",
                            "core.quotepath=false",
                            "status",
                            "--porcelain=v2",
                            "-z",
                        ]
                    }
                ),
            ),
            ResponseFunctionToolCall(
                type="function_call",
                name=build_mcp_function(self._server, DOCKER_EXEC_TOOL_NAME),
                call_id="bootstrap:stat",
                arguments=json.dumps(
                    {
                        "cmd": [
                            "git",
                            "-c",
                            "color.ui=false",
                            "-c",
                            "core.quotepath=false",
                            "--no-pager",
                            "diff",
                            "--staged",
                            "--stat",
                            "--find-renames",
                        ]
                    }
                ),
            ),
        ]

    def on_before_sample(self):  # type: ignore[override]
        if self._state.result is not None:
            return Abort()
        self._step += 1
        if self._step == 1:
            return SyntheticAction(outputs=self._bootstrap)
        return Continue(RequireAny())


async def generate_commit_message_minicodex(model: str = "gpt-5") -> str:
    """Run MiniCodex with docker_exec + submit_commit_message MCP servers and return the commit message text."""
    # Wire a RO docker MCP with the Git repo root mounted at /workspace
    repo_root = Path(Repo(Path.cwd(), search_parent_directories=True).working_tree_dir)
    wiring = properties_docker_spec(repo_root, mount_properties=False)

    submit_state = SubmitState()
    submit_server = make_submit_server(submit_state)
    specs = {
        wiring.server_name: wiring.server_spec,
        "submit_commit_message": make_inproc_slot_spec(submit_server),
    }

    prompt = (
        "You are an expert at writing high-quality git commit messages.\n\n"
        "Use tools to inspect the repository (git status, staged diff, and per-file diffs as needed).\n"
        "Then produce a concise, imperative subject (<=72 chars) and an optional body with wrapped lines.\n"
        "Finally, call submit_commit_message.submit_commit_message with subject and body."
    )

    # Initialize global logging (console at WARNING; file at ADGN_LOG_DIR if set)
    configure_logging()
    # Silence MiniCodex/structlog chatter for git_commit_ai invocations
    for name in ("mini_codex", "MiniCodex", "adgn_llm.mini_codex", "mcp", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system="You are a code agent. Be concise.",
            client=AsyncOpenAI(),
            handlers=[
                CommitController(submit_state, wiring.server_name),
            ],
            parallel_tool_calls=True,
        )
        await agent.run(prompt)

    assert submit_state.result is not None, "submit_commit_message not called"
    cm = submit_state.result
    return cm.subject if not cm.body else f"{cm.subject}\n\n{cm.body}"
