from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from fastmcp.client import Client
from pydantic import BaseModel, Field
import pygit2

from adgn.agent.agent import MiniCodex
from adgn.agent.bootstrap import TypedBootstrapBuilder
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.handler import BaseHandler, SequenceHandler
from adgn.agent.loop_control import Abort, InjectItems, NoAction, RequireAnyTool
from adgn.mcp._shared.constants import SUBMIT_COMMIT_MESSAGE_SERVER_NAME
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.git_ro.server import (
    GIT_RO_SERVER_NAME,
    DiffFormat,
    DiffInput,
    ListSlice,
    ShowInput,
    StatusInput,
    TextSlice,
    attach_git_ro,
)
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import FunctionCallItem


def make_commit_bootstrap_calls(
    builder: TypedBootstrapBuilder,
    server: str,
    *,
    amend: bool = False,
    staged_limit: int = 2000,
    patch_slice_chars: int = 50000,
) -> list[FunctionCallItem]:
    """Build bootstrap calls for commit message generation.

    Args:
        builder: TypedBootstrapBuilder instance
        server: Git MCP server name
        amend: If True, include git_show and diff for HEAD (for amending commits)
        staged_limit: Maximum number of staged files to list
        patch_slice_chars: Maximum characters for patch output

    Returns:
        List of bootstrap function call items
    """
    calls = [
        builder.call(server, "git_status", StatusInput(list_slice=ListSlice(offset=0, limit=1000))),
        builder.call(
            server,
            "git_diff",
            DiffInput(
                format=DiffFormat.NAME_STATUS,
                staged=True,
                find_renames=True,
                list_slice=ListSlice(offset=0, limit=staged_limit),
            ),
        ),
        builder.call(
            server,
            "git_diff",
            DiffInput(
                format=DiffFormat.STAT,
                staged=True,
                find_renames=True,
                list_slice=ListSlice(offset=0, limit=staged_limit),
            ),
        ),
        builder.call(
            server,
            "git_diff",
            DiffInput(
                format=DiffFormat.PATCH,
                staged=True,
                unified=0,
                slice=TextSlice(offset_chars=0, max_chars=patch_slice_chars),
            ),
        ),
    ]

    if amend:
        calls.extend(
            [
                builder.call(
                    server,
                    "git_show",
                    ShowInput(object="HEAD", format=DiffFormat.PATCH, slice=TextSlice(offset_chars=0, max_chars=50000)),
                ),
                builder.call(
                    server,
                    "git_diff",
                    DiffInput(
                        format=DiffFormat.PATCH,
                        rev_a="HEAD^",
                        rev_b="HEAD",
                        unified=0,
                        slice=TextSlice(offset_chars=0, max_chars=50000),
                    ),
                ),
            ]
        )

    return calls


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
    m = NotifyingFastMCP("submit_commit_message", instructions="Submit commit message (subject/body) and finish")

    @m.flat_model()
    def submit_commit_message(payload: CommitMessage) -> SimpleOk:
        state.result = payload
        return SimpleOk(ok=True)

    return m


class CommitController(BaseHandler):
    """Manages commit flow: bootstrap git calls → require tools → submit.

    Delegates bootstrap injection to SequenceHandler, then monitors for submission.
    """

    def __init__(self, state: SubmitState, bootstrap_handler: BaseHandler) -> None:
        self._state = state
        self._bootstrap_handler = bootstrap_handler

    def on_before_sample(self):
        # Stop immediately once submit_commit_message was called
        if self._state.result is not None:
            return Abort()

        # Delegate bootstrap to handler
        decision = self._bootstrap_handler.on_before_sample()
        if decision is not None:
            return decision

        return NoAction()


async def generate_commit_message_minicodex(
    repo: pygit2.Repository, model: str, *, debug: bool = False, amend: bool = False
) -> str:
    """Run MiniCodex with docker_exec + submit_commit_message MCP servers and return the commit message text."""
    repo_root = Path(repo.workdir or repo.path).parent

    submit_state = SubmitState()

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

    # Build compositor, mount servers
    comp = Compositor("compositor")
    git_server = await attach_git_ro(comp, repo_root)
    await comp.mount_inproc(SUBMIT_COMMIT_MESSAGE_SERVER_NAME, make_submit_server(submit_state))

    # Build bootstrap calls
    builder = TypedBootstrapBuilder.for_server(git_server)
    bootstrap_calls = make_commit_bootstrap_calls(builder, GIT_RO_SERVER_NAME, amend=amend)
    bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

    handlers: list[BaseHandler] = [CommitController(submit_state, bootstrap)]
    if debug:
        handlers.append(DisplayEventsHandler(write=lambda s: print(s, file=sys.stderr)))

    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system="You are a code agent. Be concise.",
            client=build_client(model),
            handlers=handlers,
            parallel_tool_calls=True,
            tool_policy=RequireAnyTool(),
        )
        await agent.run(prompt)

    assert submit_state.result is not None, "submit_commit_message not called"
    cm = submit_state.result
    return cm.subject if not cm.body else f"{cm.subject}\n\n{cm.body}"
