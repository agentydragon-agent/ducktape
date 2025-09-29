import json
import logging
import re
from typing import Iterable, Literal, cast
from urllib.parse import urlparse

from adgn.llm.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.llm.mcp._shared.fastmcp_helpers import mcp_flat_model
from adgn.llm.mini_codex.approvals import (
    ApprovalPolicyEngine,
    ApprovalStatus,
    ProposalSnapshot,
)
from mcp.server.fastmcp.server import MCPResource, ReadResourceContents
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, TypeAdapter

# Approval policy resource scheme and helpers
APPROVAL_SCHEME = "approval-policy"
POLICY_NAME = "policy.py"
PROPOSALS_HOST = "proposals"
PROPOSAL_SUFFIX = ".json"
PROPOSAL_PATH_RE = re.compile(rf"/([A-Za-z0-9_-]+){re.escape(PROPOSAL_SUFFIX)}$")
_AnyUrlAdapter = TypeAdapter(AnyUrl)
POLICY_URI: AnyUrl = _AnyUrlAdapter.validate_python(
    f"{APPROVAL_SCHEME}://{POLICY_NAME}"
)

logger = logging.getLogger("adgn.mcp")


class ProposeInput(BaseModel):
    source: str = Field(description="Python source code for the approval policy proposal")
    rationale: str | None = Field(default=None, description="Optional rationale for the proposal")
    model_config = ConfigDict(extra="forbid")


class WithdrawInput(BaseModel):
    proposal_id: str = Field(description="ID of the proposal to withdraw")
    model_config = ConfigDict(extra="forbid")


class GetStatusInput(BaseModel):
    """Empty input for get_status (keeps single-arg typed pattern consistent)."""
    model_config = ConfigDict(extra="forbid")


class ProposalCreated(BaseModel):
    proposal_id: str


class OperationResult(BaseModel):
    ok: bool
    error: str | None = None


def make_proposal_uri(pid: str) -> AnyUrl:
    return _AnyUrlAdapter.validate_python(
        f"{APPROVAL_SCHEME}://{PROPOSALS_HOST}/{pid}{PROPOSAL_SUFFIX}"
    )


class ApprovalPolicyServer(NotifyingFastMCP):
    """MCP server facade over ApprovalPolicyEngine that emits protocol notifications.

    Testing aid: exposes await_last_broadcast() to await delivery of the most
    recent broadcast task deterministically instead of sleeping.
    """

    _last_broadcast_task = None
    """MCP server facade over ApprovalPolicyEngine that emits protocol notifications.

    Resources (conceptual URIs; discovery optional initially):
      - approval-policy://policy.py
      - approval-policy://proposals/{id}.json

    Tools:
      - propose(source: str, rationale?: str) -> { proposal_id }
      - withdraw(proposal_id: str) -> { ok }
      - get_status() -> engine status dict

    Note: apply() is intentionally NOT exposed as a tool. Only humans should
    approve/reject proposals through the UI or other control interfaces.

    Notes:
      - On engine changes, ResourceUpdatedNotification is emitted via broadcast_resource_updated(uri)
      - In v1 we do not implement list_resources/read_resource; clients can still receive
        resource-update notifications and choose to read via a known URI if wired later.
    """

    def __init__(
        self, engine: ApprovalPolicyEngine, *, name: str = "approval_policy"
    ) -> None:
        super().__init__(
            name=name,
            instructions=(
                "Approval policy system controlling which tools are auto-approved, denied, or require manual approval.\n"
                "- Read approval-policy://policy.py to see the current policy code\n"
                "- Use propose() to submit policy changes for review\n"
                "- Policy must be valid Python code defining a decide(ctx) function\n"
                "- Policy decides: 'allow' (auto-approve), 'ask' (manual approval), 'deny_continue' (deny but continue), 'deny_abort' (deny and abort)\n"
                "- Default policy allows UI tools and approval management, asks for everything else"
            ),
        )
        self._engine = engine

        # Bridge engine notifications → MCP protocol resource updates
        def _notify(uri: str) -> None:
            # Fire-and-forget; schedule broadcast on the event loop
            import asyncio

            logger.debug("engine notify uri=%s", uri)
            task = asyncio.create_task(self.broadcast_resource_updated(uri))
            ApprovalPolicyServer._last_broadcast_task = task

        # Install notifier hook on the engine (required wiring)
        self._engine.set_notifier(_notify)

        # Register tools
        self._register_tools()

    def _register_tools(self) -> None:
        """Register tools with proper type annotations."""
        # Register the instance methods as tools
        self.tool(
            name="propose",
            title="Propose policy change",
            description="Submit a new proposal for approval policy changes. Policy must be valid Python code.",
            structured_output=True,
        )(self.propose_tool)

        self.tool(
            name="withdraw",
            title="Withdraw proposal",
            description="Withdraw an existing proposal",
            structured_output=True,
        )(self.withdraw_tool)

        self.tool(
            name="get_status",
            title="Get approval status",
            description="Get current approval policy status and proposals",
            structured_output=True,
        )(self.get_status_tool)

    async def propose_tool(self, source: str, rationale: str | None = None) -> ProposalCreated:
        return await self._propose(source, rationale)

    async def withdraw_tool(self, proposal_id: str) -> OperationResult:
        return await self._withdraw(proposal_id)

    async def get_status_tool(self) -> ApprovalStatus:
        return await self._get_status()

    # Tool implementations
    async def _propose(self, source: str, rationale: str | None = None) -> ProposalCreated:
        pid = self._engine.create_proposal(source=source, rationale=rationale)
        # Engine will trigger _notify(proposals/{id}.json)
        return ProposalCreated(proposal_id=pid)

    async def _withdraw(self, proposal_id: str) -> OperationResult:
        self._engine.withdraw(proposal_id)
        return OperationResult(ok=True)

    async def _apply(
        self, proposal_id: str, decision: Literal["approve", "reject"]
    ) -> OperationResult:
        self._engine.apply(proposal_id, decision)
        # On approve, engine.set_policy() is called which will trigger _notify(policy.py)
        return OperationResult(ok=True)

    async def _get_status(self) -> ApprovalStatus:
        return self._engine.get_status()

    # ---- Resources (dynamic, backed by engine) ----
    async def list_resources(self) -> list[MCPResource]:
        # Server owns resource URIs; engine provides data only
        resources: list[MCPResource] = []
        # policy.py
        resources.append(
            MCPResource(
                uri=POLICY_URI,
                name=POLICY_NAME,
                mimeType="text/plain",
            )
        )
        # proposals/{id}.json from engine status
        status = self._engine.get_status()
        for pr in status.proposals:
            pid = pr.id
            resources.append(
                MCPResource(
                    uri=make_proposal_uri(pid),
                    name=f"{pid}{PROPOSAL_SUFFIX}",
                    mimeType="application/json",
                )
            )
        return resources

    async def read_resource(
        self, uri: AnyUrl | str
    ) -> str | Iterable[ReadResourceContents]:
        # Conform to low-level server expectation: return str | bytes | Iterable[ReadResourceContents]
        u = str(uri)
        parsed = urlparse(u)
        if parsed.scheme != APPROVAL_SCHEME:
            raise KeyError(u)
        host = parsed.netloc
        path = parsed.path or ""
        if host == POLICY_NAME:
            source, _ver = self._engine.get_policy()
            return cast(
                str, source
            )  # low-level wraps into TextResourceContents with text/plain
        if host == PROPOSALS_HOST:
            m = PROPOSAL_PATH_RE.fullmatch(path)
            if not m:
                raise KeyError(u)
            pid = m.group(1)
            proposal: ProposalSnapshot = self._engine.get_proposal(pid)
            proposal_json: str = json.dumps(
                proposal.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
            )
            return proposal_json
        raise KeyError(u)

    async def await_last_broadcast(self) -> None:
        t = ApprovalPolicyServer._last_broadcast_task
        if t is not None and not t.done():
            try:
                await t
            except Exception:
                pass
