from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys

from git import Repo
from mcp.server.fastmcp import FastMCP
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall
from pydantic import BaseModel, Field

from adgn.llm.logging_config import configure_logging
from adgn.llm.mcp.git_ro.server import (
    GIT_RO_SERVER_NAME,
    DiffFormat,
    DiffInput,
    ListSlice,
    ShowInput,
    make_git_ro_server,
)
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import BaseHandler
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.loop_control import (
    Abort,
    Continue,
    RequireAny,
)
from adgn.llm.mini_codex.mcp_manager import McpManager, build_mcp_function


def _default_bootstrap(
    server: str,
    *,
    staged_limit: int = 2000,
    patch_slice_chars: int = 50000,
) -> list[ResponseFunctionToolCall]:
    """Build the default list of bootstrap tool calls for a commit flow.

    Returns a list of ResponseFunctionToolCall objects representing the initial
    set of MCP function calls an agent should see when composing a commit
    message. Parameters control pagination sizes used for heavy payloads.
    """
    return [
        ResponseFunctionToolCall(
            type="function_call",
            name=build_mcp_function(server, "git_status"),
            call_id="bootstrap:status",
            arguments=json.dumps({}),
        ),
        ResponseFunctionToolCall(
            type="function_call",
            name=build_mcp_function(server, "git_diff"),
            call_id="bootstrap:diff-name-status",
            arguments=json.dumps(
                {
                    "payload": DiffInput(
                        format=DiffFormat.NAME_STATUS,
                        staged=True,
                        find_renames=True,
                        list_slice=ListSlice(offset=0, limit=staged_limit),
                    ).model_dump(),
                },
            ),
        ),
        ResponseFunctionToolCall(
            type="function_call",
            name=build_mcp_function(server, "git_diff"),
            call_id="bootstrap:diff-stat",
            arguments=json.dumps(
                {
                    "payload": DiffInput(
                        format=DiffFormat.STAT,
                        staged=True,
                        find_renames=True,
                        list_slice=ListSlice(offset=0, limit=staged_limit),
                    ).model_dump(),
                },
            ),
        ),
        ResponseFunctionToolCall(
            type="function_call",
            name=build_mcp_function(server, "git_diff"),
            call_id="bootstrap:diff-patch",
            arguments=json.dumps(
                {
                    "payload": {
                        "format": "patch",
                        "staged": True,
                        "unified": 0,
                        "slice": {"offset_chars": 0, "max_chars": patch_slice_chars},
                    },
                },
            ),
        ),
    ]


class CommitMessage(BaseModel):
    """Minimal commit message payload."""

    subject: str = Field(..., description="<=72 chars, imperative mood")
    body: str | None = Field(
        default=None,
        description="Optional body. If given, will be auto-appended to header to form full commit message.",
    )


@dataclass
class SubmitState:
    result: CommitMessage | None = None


def make_submit_server(state: SubmitState):
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
    """Emit bootstrap git calls in parallel on first turn; then require tools until submit.

    The controller can be configured with `amend=True` to include additional
    bootstrap calls that inspect the commit being amended (HEAD) and the original
    commit diff (HEAD^..HEAD) so the agent has explicit amendment context.
    """

    def __init__(
        self,
        state: SubmitState,
        server_name: str,
        amend: bool = False,
    ) -> None:
        self._state = state
        self._server = server_name
        self._step = 0
        # Bootstrap with read-only Git MCP tools (structured payloads)
        self._bootstrap = _default_bootstrap(self._server)

        # If amending, append dedicated bootstrap calls for the amended commit and its original diff
        if amend:
            extra_boots = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=build_mcp_function(self._server, "git_show"),
                    call_id="bootstrap:show-head",
                    arguments=json.dumps(
                        {
                            "payload": ShowInput(
                                object="HEAD",
                                format=DiffFormat.PATCH,
                                slice=ListSlice(offset=0, max_chars=50000),
                            ).model_dump(),
                        },
                    ),
                ),
                ResponseFunctionToolCall(
                    type="function_call",
                    name=build_mcp_function(self._server, "git_diff"),
                    call_id="bootstrap:orig-diff",
                    arguments=json.dumps(
                        {
                            "payload": DiffInput(
                                format=DiffFormat.PATCH,
                                rev_a="HEAD^",
                                rev_b="HEAD",
                                unified=0,
                                slice=ListSlice(offset=0, max_chars=50000),
                            ).model_dump(),
                        },
                    ),
                ),
            ]
            self._bootstrap.extend(extra_boots)

    def on_before_sample(self):  # type: ignore[override]
        if self._state.result is not None:
            return Abort()
        self._step += 1
        if self._step == 1:
            return Continue(
                tool_policy=RequireAny(),
                inserts_input=tuple(self._bootstrap),
                skip_sampling=True,
            )
        return Continue(RequireAny())


async def generate_commit_message_minicodex(
    model: str,
    *,
    debug: bool = False,
    amend: bool = False,
) -> str:
    """Run MiniCodex with docker_exec + submit_commit_message MCP servers and return the commit message text."""
    # Wire an in-proc read-only Git MCP server bound to the current repo
    worktree_dir = Repo(Path.cwd(), search_parent_directories=True).working_tree_dir
    assert worktree_dir is not None, "Unable to locate git working tree directory"
    repo_root = Path(worktree_dir)

    submit_state = SubmitState()
    submit_server = make_submit_server(submit_state)
    specs = {
        GIT_RO_SERVER_NAME: make_inproc_slot_spec(make_git_ro_server(repo_root)),
        "submit_commit_message": make_inproc_slot_spec(submit_server),
    }

    def _build_commit_prompt(is_amend: bool) -> str:
        base = "You are an expert at writing high-quality git commit messages.\n\n"
        common_tail = (
            "Produce a concise, imperative subject (<=80 chars) and optional body "
            "with wrapped lines; then call submit_commit_message. When reviewing changes, "
            "use git_diff with format=name-status and format=stat to understand the file list and rename map, "
            "then request per-file patches by passing paths=['<file>'] with format=patch and a small slice (e.g. max_chars=8000)."
        )
        if is_amend:
            middle = (
                "You are AMENDING the last commit. Inspect the original commit (HEAD) and "
                "its diff against its parent, then update the commit message to reflect "
                "the staged changes being applied.\n"
            )
        else:
            middle = "You are COMMITTING the staged diff. Inspect the staged changes and then "
        return base + middle + common_tail

    prompt = _build_commit_prompt(amend)

    # Initialize global logging (console at WARNING; file at ADGN_LOG_DIR if set)
    configure_logging()
    # Silence MiniCodex/structlog chatter for git_commit_ai invocations
    for name in ("mini_codex", "MiniCodex", "adgn_llm.mini_codex", "mcp", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)

    handlers: list[BaseHandler] = [
        CommitController(submit_state, GIT_RO_SERVER_NAME, amend=amend),
    ]
    if debug:
        handlers.insert(
            0,
            DisplayEventsHandler(write=lambda s: print(s, file=sys.stderr)),
        )

    async with McpManager(specs) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system="You are a code agent. Be concise.",
            client=AsyncOpenAI(),
            handlers=handlers,
            parallel_tool_calls=True,
        )
        await agent.run(prompt)

    assert submit_state.result is not None, "submit_commit_message not called"
    cm = submit_state.result
    return cm.subject if not cm.body else f"{cm.subject}\n\n{cm.body}"
