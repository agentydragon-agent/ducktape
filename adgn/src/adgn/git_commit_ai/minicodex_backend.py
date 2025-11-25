from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from fastmcp.client import Client
from pydantic import BaseModel, Field
import pygit2

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.loop_control import Abort, Continue, RequireAny
from adgn.agent.reducer import BaseHandler
from adgn.mcp._shared.constants import SUBMIT_COMMIT_MESSAGE_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
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
from adgn.openai_utils.builders import ItemFactory
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import FunctionCallItem


def _default_bootstrap(
    server: str, *, staged_limit: int = 2000, patch_slice_chars: int = 50000
) -> list[FunctionCallItem]:
    """Build the default list of bootstrap tool calls for a commit flow.

    Returns initial function calls agent should start out having executed when composing
    a commit message. Parameters control pagination sizes used for heavy payloads.
    """
    f = ItemFactory(call_id_prefix="bootstrap")
    return [
        f.tool_call(
            name=build_mcp_function(server, "git_status"),
            arguments=StatusInput(list_slice=ListSlice(offset=0, limit=1000)).model_dump(),
            call_id="bootstrap:status",
        ),
        f.tool_call(
            name=build_mcp_function(server, "git_diff"),
            arguments=DiffInput(
                format=DiffFormat.NAME_STATUS,
                staged=True,
                find_renames=True,
                list_slice=ListSlice(offset=0, limit=staged_limit),
            ).model_dump(),
            call_id="bootstrap:diff-name-status",
        ),
        f.tool_call(
            name=build_mcp_function(server, "git_diff"),
            arguments=DiffInput(
                format=DiffFormat.STAT,
                staged=True,
                find_renames=True,
                list_slice=ListSlice(offset=0, limit=staged_limit),
            ).model_dump(),
            call_id="bootstrap:diff-stat",
        ),
        f.tool_call(
            name=build_mcp_function(server, "git_diff"),
            arguments=DiffInput(
                format=DiffFormat.PATCH,
                staged=True,
                unified=0,
                slice=TextSlice(offset_chars=0, max_chars=patch_slice_chars),
            ).model_dump(),
            call_id="bootstrap:diff-patch",
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
    m = NotifyingFastMCP("submit_commit_message", instructions="Submit commit message (subject/body) and finish")

    @m.flat_model()
    def submit_commit_message(payload: CommitMessage) -> SimpleOk:
        state.result = payload
        return SimpleOk(ok=True)

    return m


class CommitController(BaseHandler):
    """Emit bootstrap git calls in parallel on first turn; then require tools until submit.

    The controller can be configured with `amend=True` to include additional
    bootstrap calls that inspect the commit being amended (HEAD) and the original
    commit diff (HEAD^..HEAD) so the agent has explicit amendment context.
    """

    def __init__(self, state: SubmitState, server_name: str, amend: bool = False) -> None:
        self._state = state
        self._server = server_name
        self._step = 0
        # Bootstrap with read-only Git MCP tools (structured payloads)
        self._bootstrap = _default_bootstrap(self._server)

        # If amending, append dedicated bootstrap calls for the amended commit and its original diff
        if amend:
            f = ItemFactory(call_id_prefix="bootstrap")
            extra_boots = [
                f.tool_call(
                    name=build_mcp_function(self._server, "git_show"),
                    arguments=ShowInput(
                        object="HEAD", format=DiffFormat.PATCH, slice=TextSlice(offset_chars=0, max_chars=50000)
                    ).model_dump(),
                    call_id="bootstrap:show-head",
                ),
                f.tool_call(
                    name=build_mcp_function(self._server, "git_diff"),
                    arguments=DiffInput(
                        format=DiffFormat.PATCH,
                        rev_a="HEAD^",
                        rev_b="HEAD",
                        unified=0,
                        slice=TextSlice(offset_chars=0, max_chars=50000),
                    ).model_dump(),
                    call_id="bootstrap:orig-diff",
                ),
            ]
            self._bootstrap.extend(extra_boots)

    def on_before_sample(self):
        if self._state.result is not None:
            return Abort()
        self._step += 1
        if self._step == 1:
            return Continue(tool_policy=RequireAny(), inserts_input=tuple(self._bootstrap), skip_sampling=True)
        return Continue(RequireAny())


async def generate_commit_message_minicodex(model: str, *, debug: bool = False, amend: bool = False) -> str:
    """Run MiniCodex with docker_exec + submit_commit_message MCP servers and return the commit message text."""
    # Wire an in-proc read-only Git MCP server bound to the current repo
    gitdir = pygit2.discover_repository(Path.cwd())
    assert gitdir, "Unable to locate git repository"
    repo = pygit2.Repository(gitdir)
    repo_root = Path(repo.workdir or Path(gitdir).parent)

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

    handlers: list[BaseHandler] = [CommitController(submit_state, GIT_RO_SERVER_NAME, amend=amend)]
    if debug:
        handlers.insert(0, DisplayEventsHandler(write=lambda s: print(s, file=sys.stderr)))

    # Build compositor, mount servers, and run agent with a client
    comp = Compositor("compositor")
    await attach_git_ro(comp, repo_root)
    await comp.mount_inproc(SUBMIT_COMMIT_MESSAGE_SERVER_NAME, make_submit_server(submit_state))
    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            model=model,
            mcp_client=mcp_client,
            system="You are a code agent. Be concise.",
            client=build_client(model),
            handlers=handlers,
            parallel_tool_calls=True,
        )
        await agent.run(prompt)

    assert submit_state.result is not None, "submit_commit_message not called"
    cm = submit_state.result
    return cm.subject if not cm.body else f"{cm.subject}\n\n{cm.body}"
