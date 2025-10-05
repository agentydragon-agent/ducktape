import asyncio
from datetime import datetime, timezone
import importlib
from importlib import resources as il_resources
import inspect
import json
import logging
import re
from typing import Any, Callable, Coroutine, Iterable, Literal, cast
from urllib.parse import urlparse

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from adgn.agent.approvals import (
    ApprovalPolicyEngine,
    ApprovalStatus,
    ProposalSnapshot,
)
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from mcp.server.fastmcp.server import MCPResource, ReadResourceContents

# Approval policy resource scheme and helpers
APPROVAL_SCHEME = "approval-policy"
POLICY_NAME = "policy.py"
PROPOSALS_HOST = "proposals"
MODULES_HOST = "adgn"  # default top-level namespace used in list_resources
# Generic module-source scheme (mirrors import paths): module://<slashed module path>.py
MODULE_SCHEME = "module"
PROPOSAL_SUFFIX = ".json"
PROPOSAL_PATH_RE = re.compile(rf"/([A-Za-z0-9_-]+){re.escape(PROPOSAL_SUFFIX)}$")
_AnyUrlAdapter = TypeAdapter(AnyUrl)
POLICY_URI: AnyUrl = _AnyUrlAdapter.validate_python(f"{APPROVAL_SCHEME}://{POLICY_NAME}")

logger = logging.getLogger(__name__)


def _load_instructions() -> str:
    # Fail hard if the packaged instructions are missing or unreadable.
    return il_resources.files(__package__).joinpath("instructions.md").read_text(encoding="utf-8")


class ProposalSummary(BaseModel):
    id: str
    status: Literal["open", "withdrawn", "approved", "rejected"]
    rationale: str | None = None


class ApprovalStatusSummary(BaseModel):
    version: int
    open_proposal: str | None
    proposals: list[ProposalSummary]


class ProposeInput(BaseModel):
    policy_python_code: str | None = Field(
        default=None,
        description=(
            "Full Python source code of the approval policy. Must define a top-level "
            "decide(ctx) -> (PolicyDecision, rationale:str) and a TEST_CASES constant "
            "(list of (ApprovalContext, PolicyDecision)). "
            "The code is compiled only at propose time (no execution); tests execute upon approval."
        ),
    )
    patch_unified: str | None = Field(
        default=None,
        description=(
            "Unified diff patch to apply to the CURRENT policy (single file).\n"
            "Requirements:\n"
            "- Must be a standard unified diff with at least one hunk header: '@@ -old_start,old_len +new_start,new_len @@'\n"
            "- May include optional file headers ('--- policy.py' / '+++ policy.py'); they are ignored\n"
            "- Applies to the in-memory policy.py content; the result MUST change the policy (no-ops are rejected)\n"
            "Example minimal hunk that inserts a header line at top:\n"
            "@@ -1,0 +1,1 @@\n"
            "+# Policy header (patched)\n"
        ),
    )
    rationale: str | None = Field(default=None, description="Optional rationale for the proposal")
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _one_of_source_or_patch(self) -> "ProposeInput":
        has_src = bool(self.policy_python_code and self.policy_python_code.strip())
        has_patch = bool(self.patch_unified and self.patch_unified.strip())
        if has_src == has_patch:
            # Either both provided or neither
            raise ValueError("Exactly one of policy_python_code or patch_unified must be provided")
        return self


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
      - propose(policy_python_code | patch_unified, rationale?): open a proposal to replace the policy. Provide exactly one of:\n"
      - "   * policy_python_code: full Python source defining decide(ctx) and TEST_CASES\n"
      - "   * patch_unified: unified diff to apply to the CURRENT policy (single file)\n"
      - "   Returns { proposal_id }.\n"
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
        self,
        engine: ApprovalPolicyEngine,
        *,
        name: str = "approval_policy",
        agent_id: str | None = None,
        persistence=None,
        on_change: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        super().__init__(name=name, instructions=_load_instructions())
        self._engine = engine
        self._agent_id = agent_id
        self._persistence = persistence
        self._on_change = on_change

        # Bridge engine notifications → MCP protocol resource updates
        def _notify(uri: str) -> None:
            # Fire-and-forget; schedule broadcast on the event loop

            logger.debug("engine notify uri=%s", uri)
            task = asyncio.create_task(self.broadcast_resource_updated(uri))
            ApprovalPolicyServer._last_broadcast_task = task
            if self._on_change is not None:
                # Trigger UI snapshot push (do not await here)
                asyncio.create_task(self._on_change())

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
            description=(
                "Submit a new proposal for approval policy changes.\n"
                "Provide exactly one of:\n"
                "  (a) policy_python_code: full Python source that defines decide(ctx) and TEST_CASES; or\n"
                "  (b) patch_unified: a standard single-file unified diff applied to the CURRENT policy.\n"
                "Patch format details: include at least one hunk header of the form '@@ -old_start,old_len +new_start,new_len @@';\n"
                "file header lines ('---', '+++') are optional. The patch must produce a different policy; no-op patches are rejected.\n"
                "Policy code is compiled only during propose; tests execute on approval and at runtime."
            ),
            structured_output=True,
            flat=True,
            flat_input_model=ProposeInput,
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
            description=(
                "Get current approval status summary: version, open_proposal id, and proposals metadata (id, status, rationale).\n"
                "Does not return policy or proposal source; read resources via approval-policy URIs if needed."
            ),
            structured_output=True,
        )(self.get_status_tool)

    async def propose_tool(self, payload: ProposeInput) -> ProposalCreated:
        """Propose a policy change with transactional semantics.

        Invariants:
        - If the tool call fails (raises), no proposal remains open in the engine.
        - Persistence is attempted only after the engine accepts the proposal; on
          persistence failure the engine change is rolled back.
        """
        # Choose source from either direct code or applying a unified patch
        source: str
        if payload.policy_python_code and payload.policy_python_code.strip():
            source = payload.policy_python_code
        else:
            current, _ver = self._engine.get_policy()
            if not payload.patch_unified:
                raise ValueError(
                    "patch_unified is required when policy_python_code is not provided"
                )
            # Apply unified patch; must contain at least one hunk and produce a change
            patched = apply_unified_patch(current, payload.patch_unified)
            if patched == current:
                raise ValueError(
                    "patch_unified did not change the policy source; provide a patch with actual modifications"
                )
            source = patched

        # Compute a sequential id up-front when persistence is available (optional)
        next_id: str | None = None
        if self._persistence is not None and self._agent_id is not None:
            rows = await self._persistence.list_proposals(self._agent_id)
            max_n = 0
            for r in rows:
                pid0 = str(r.get("id") or "")
                if pid0.startswith("p-"):
                    num = pid0[2:]
                    if num.isdigit():
                        max_n = max(max_n, int(num))
            next_id = f"p-{max_n + 1}"

        pid: str | None = None
        try:
            # Create proposal in engine (validates syntax and required symbols)
            pid = self._engine.create_proposal(
                source=source, rationale=payload.rationale, proposal_id=next_id
            )
            # Persist only after engine accepts the proposal. If this fails, rollback engine.
            if self._persistence is not None and self._agent_id is not None:
                await self._persistence.create_proposal(
                    self._agent_id,
                    proposal_id=pid,
                    source=source,
                    rationale=payload.rationale,
                    created_at=datetime.now(timezone.utc),
                )
            return ProposalCreated(proposal_id=pid)
        except Exception:
            # Roll back engine state on any error that occurs after engine creation
            if pid is not None:
                try:
                    self._engine.withdraw(pid)
                except Exception:
                    logger.debug("rollback withdraw failed for %s", pid, exc_info=True)
            # Propagate so MCP layer marks call as error
            raise

    async def withdraw_tool(self, proposal_id: str) -> OperationResult:
        return await self._withdraw(proposal_id)

    async def get_status_tool(self) -> ApprovalStatusSummary:
        # Convert engine status into a summary that excludes content already exposed as resources
        status = await self._get_status()
        summaries: list[ProposalSummary] = []
        for p in status.proposals:
            summaries.append(
                ProposalSummary(
                    id=p.id,
                    status=p.status,
                    rationale=p.rationale,
                )
            )
        return ApprovalStatusSummary(
            version=status.version,
            open_proposal=status.open_proposal,
            proposals=summaries,
        )

    # Tool implementations
    async def _propose(self, source: str, rationale: str | None = None) -> ProposalCreated:
        # Engine already performs compile-only validation (syntax) on create_proposal.
        # Generate a sequential id per agent when persistence/agent_id are available.
        next_id: str | None = None
        if self._persistence is not None and self._agent_id is not None:
            # Compute next sequential id of the form 'p-<n>' within this agent
            rows = await self._persistence.list_proposals(self._agent_id)
            max_n = 0
            for r in rows:
                pid = str(r.get("id") or "")
                if pid.startswith("p-"):
                    num = pid[2:]
                    if num.isdigit():
                        max_n = max(max_n, int(num))
            next_id = f"p-{max_n + 1}"
        pid = self._engine.create_proposal(source=source, rationale=rationale, proposal_id=next_id)
        # Persist proposal per agent if available
        if self._persistence is not None and self._agent_id is not None:
            await self._persistence.create_proposal(
                self._agent_id,
                proposal_id=pid,
                source=source,
                rationale=rationale,
                created_at=datetime.now(timezone.utc),
            )
        # Engine will trigger _notify(proposals/{id}.json)
        return ProposalCreated(proposal_id=pid)

    async def _withdraw(self, proposal_id: str) -> OperationResult:
        self._engine.withdraw(proposal_id)
        if self._persistence is not None and self._agent_id is not None:
            await self._persistence.set_proposal_status(
                self._agent_id,
                proposal_id=proposal_id,
                status="withdrawn",
                decided_at=datetime.now(timezone.utc),
            )
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
        # module source exports mirrored by import path (module://<slashed module path>.py)
        resources.append(
            MCPResource(
                uri=_AnyUrlAdapter.validate_python(
                    f"{MODULE_SCHEME}://{MODULES_HOST}/agent/approvals.py"
                ),
                name="module://adgn/agent/approvals.py",
                mimeType="text/plain",
            )
        )
        resources.append(
            MCPResource(
                uri=_AnyUrlAdapter.validate_python(
                    f"{MODULE_SCHEME}://{MODULES_HOST}/seatbelt/model.py"
                ),
                name="module://adgn/seatbelt/model.py",
                mimeType="text/plain",
            )
        )
        return resources

    async def read_resource(self, uri: AnyUrl | str) -> Iterable[ReadResourceContents]:
        u = str(uri)
        parsed = urlparse(u)
        scheme = parsed.scheme
        host = parsed.netloc
        path = parsed.path or ""
        if scheme == APPROVAL_SCHEME:
            if host == POLICY_NAME:
                source, _ver = self._engine.get_policy()
                return [ReadResourceContents(content=cast(str, source), mime_type="text/plain")]
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
                return [ReadResourceContents(content=proposal_json, mime_type="application/json")]
            raise KeyError(u)
        if scheme == MODULE_SCHEME:
            # Convert module://<slashed module path>.py to an importable module name
            # Example: module://adgn/agent/approvals.py -> adgn.agent.approvals
            rel = parsed.netloc + ("/" + path.lstrip("/")) if parsed.netloc else path.lstrip("/")
            if not rel or not rel.endswith(".py"):
                raise KeyError(u)
            mod_name = rel[:-3].replace("/", ".")
            try:
                mod = importlib.import_module(mod_name)
                src = inspect.getsource(mod)
            except Exception:
                src = "# source unavailable"
            return [ReadResourceContents(content=src, mime_type="text/plain")]
        raise KeyError(u)

    async def await_last_broadcast(self) -> None:
        t = ApprovalPolicyServer._last_broadcast_task
        if t is not None and not t.done():
            try:
                await t
            except Exception as e:
                logger.warning("approval broadcast task failed", exc_info=e)


# --- Unified patch application helper ---


def apply_unified_patch(original: str, patch_text: str) -> str:
    """Apply a single-file unified diff patch to original and return the result.

    Supports patches with one or more @@ hunks and lines beginning with ' ', '+', or '-'.
    File header lines (---/+++/diff/index) are ignored. Raises ValueError on mismatch.
    """
    # Normalize line endings
    orig_lines = original.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Track whether original ended with newline
    orig_had_trailing_nl = original.endswith("\n")
    # Parse hunks
    lines = [ln for ln in patch_text.splitlines()]
    # Collect hunks as list of (old_start, old_len, new_start, new_len, hunk_lines)
    hunks: list[tuple[int, int, int, int, list[str]]] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("@@ ") and " @@" in ln:
            # Parse header
            header = ln
            try:
                body = header.split("@@", 2)[1].strip()  # like: -a,b +c,d
                parts = body.split()
                old_part = parts[0]  # -a,b
                new_part = parts[1]  # +c,d

                def _parse(part: str) -> tuple[int, int]:
                    # part like -a,b or +c,d; lines count may be omitted -> default 1
                    part = part.strip()
                    if not part or part[0] not in "+-":
                        raise ValueError
                    nums = part[1:].split(",")
                    start = int(nums[0])
                    length = int(nums[1]) if len(nums) > 1 else 1
                    return start, length

                old_start, old_len = _parse(old_part)
                new_start, new_len = _parse(new_part)
            except Exception as e:
                raise ValueError(f"Invalid hunk header: {header}") from e
            i += 1
            hunk_lines: list[str] = []
            # Collect following lines until next hunk/header
            while i < len(lines):
                if lines[i].startswith("@@ "):
                    break
                # Ignore file headers within hunk collection? Here, we only accept content markers
                hunk_lines.append(lines[i])
                i += 1
            hunks.append((old_start, old_len, new_start, new_len, hunk_lines))
        else:
            # Ignore non-hunk lines (file headers)
            i += 1

    # Apply hunks
    if not hunks:
        raise ValueError("No hunks found in patch; expected lines like '@@ -a,b +c,d @@'")
    new_lines: list[str] = []
    orig_index0 = 0  # 0-based index into orig_lines
    for old_start, _old_len, _new_start, _new_len, hlines in hunks:
        # Append unchanged from current pos up to (old_start - 1)
        target_index0 = max(0, old_start - 1)
        if target_index0 < orig_index0:
            raise ValueError("Patch applies hunks out of order or overlapping")
        new_lines.extend(orig_lines[orig_index0:target_index0])
        orig_index0 = target_index0
        # Now apply hunk lines
        for hl in hlines:
            if not hl:
                # Treat empty as context (shouldn't happen in proper unified diff)
                if orig_index0 >= len(orig_lines):
                    # empty context at EOF; nothing to consume
                    continue
                new_lines.append(orig_lines[orig_index0])
                orig_index0 += 1
                continue
            tag = hl[0]
            content = hl[1:]
            if tag == " ":
                # Context: must match
                if orig_index0 >= len(orig_lines):
                    raise ValueError("Patch context exceeds original length")
                if orig_lines[orig_index0] != content:
                    raise ValueError("Patch context mismatch")
                new_lines.append(content)
                orig_index0 += 1
            elif tag == "-":
                # Deletion: must match original, do not add to new_lines
                if orig_index0 >= len(orig_lines):
                    raise ValueError("Patch deletion exceeds original length")
                if orig_lines[orig_index0] != content:
                    raise ValueError("Patch deletion mismatch")
                orig_index0 += 1
            elif tag == "+":
                # Addition: append to new_lines
                new_lines.append(content)
            else:
                # Ignore metadata lines inside hunk (e.g., \ No newline at end of file)
                continue

    # Append remaining original content
    new_lines.extend(orig_lines[orig_index0:])
    result = "\n".join(new_lines)
    # Preserve EOF newline similar to original; if patch content implies newline, keep one
    if orig_had_trailing_nl and not result.endswith("\n"):
        result += "\n"
    return result
