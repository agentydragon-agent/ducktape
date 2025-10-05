from __future__ import annotations

import ast
import asyncio
import builtins as _builtins
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import json
import logging
from typing import Any, Awaitable, Literal
import uuid

# Control-plane exception raised when an approval decision requests aborting the turn
from mcp import types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.handler import (
    AbortTurnDecision,
    BaseHandler,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
    ToolCall,
)
from adgn.agent.persist import ApprovalOutcome

from .mcp_manager import build_mcp_function, parse_mcp_function

logger = logging.getLogger(__name__)


class TurnAbortRequested(Exception):
    def __init__(
        self,
        call_id: str,
        reason: str = "approval_denied",
        context: dict | None = None,
    ) -> None:
        self.call_id = call_id
        self.reason = reason
        self.context = context or {}
        super().__init__(f"Turn abort requested: {reason} (call_id={call_id})")


class ApprovalToolCall(BaseModel):
    name: str
    call_id: str
    args_json: str | None = None


class ApprovalRequest(BaseModel):
    tool_key: str
    tool_call: ApprovalToolCall


class ApprovalHub:
    """In-process rendezvous for pending approval/decision events.

    - await_decision(call_id, request) -> BeforeToolCallDecision waits until resolve() is called
    - resolve(call_id, decision) resolves the pending decision
    """

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[BeforeToolCallDecision]] = {}
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()

    async def await_decision(
        self,
        call_id: str,
        request: ApprovalRequest,
    ) -> BeforeToolCallDecision:
        async with self._lock:
            # Track the request so UIs can snapshot pending approvals
            self._requests[call_id] = request
            fut = self._futures.get(call_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                self._futures[call_id] = fut
        return await fut

    def resolve(self, call_id: str, decision: BeforeToolCallDecision) -> None:
        fut = self._futures.pop(call_id, None)
        # Remove from pending requests map when resolved
        self._requests.pop(call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(decision)


# Policy function type: given payload -> "allow" | "ask"
ApprovalMode = Literal["allow", "ask"]
ToolPolicyFn = Callable[[dict[str, Any]], ApprovalMode]


def default_allow_all_policy(_: dict[str, Any]) -> ApprovalMode:
    return "allow"


# ---- Approval Policy Engine (decoupled, in-memory; optional) ----


def validate_policy_python(source: str) -> None:
    """Validate that policy source is valid Python and includes required top-level symbols.

    Compile-only checks (no execution):
    - Source parses as valid Python
    - A top-level function named 'decide' exists
    - A top-level constant/variable named 'TEST_CASES' is defined
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Policy contains invalid Python syntax: {e}")
    except Exception as e:
        raise ValueError(f"Policy validation failed: {e}")

    has_decide = False
    has_tests = False
    for node in getattr(tree, "body", []) or []:
        if isinstance(node, ast.FunctionDef) and node.name == "decide":
            has_decide = True
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TEST_CASES":
                    has_tests = True
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == "TEST_CASES":
                has_tests = True
    if not has_decide:
        raise ValueError("policy missing top-level decide(ctx) function")
    if not has_tests:
        raise ValueError("policy missing top-level TEST_CASES constant")


@dataclass
class Proposal:
    id: str
    source: str  # Python code defining the approval policy
    status: Literal["open", "approved", "rejected", "withdrawn"]
    created_at: datetime
    decided_at: datetime | None = None
    rationale: str | None = None  # Human-readable explanation for the policy change


class ProposalSnapshot(BaseModel):
    id: str
    status: Literal["open", "withdrawn", "approved", "rejected"]
    created_at: datetime
    decided_at: datetime | None = None
    source: str = Field(description="Python code defining the approval policy")
    rationale: str | None = Field(
        default=None, description="Human-readable explanation for the policy change"
    )

    model_config = ConfigDict(from_attributes=True)


class ProposalMeta(BaseModel):
    id: str
    status: Literal["open", "withdrawn", "approved", "rejected"]
    rationale: str | None = None

    # Allow validation from Proposal dataclass without requiring extra fields
    model_config = ConfigDict(from_attributes=True)


class ApprovalStatus(BaseModel):
    version: int
    open_proposal: str | None
    proposals: list[ProposalMeta]

    model_config = ConfigDict(from_attributes=True)


# Decision enum exposed to policy code
class PolicyDecision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY_CONTINUE = "deny_continue"
    DENY_ABORT = "deny_abort"


class WellKnownServers(StrEnum):
    UI = "ui"
    APPROVAL_POLICY = "approval_policy"
    RESOURCES = "resources"
    # Exec backends
    SEATBELT_EXEC = "seatbelt_exec"


class WellKnownTools(StrEnum):
    SEND_MESSAGE = "send_message"
    END_TURN = "end_turn"
    GET_STATUS = "get_status"
    PROPOSE = "propose"
    WITHDRAW = "withdraw"
    # Common MCP tool identifiers for convenience in policies
    SANDBOX_EXEC = "sandbox_exec"  # adgn.mcp.seatbelt_exec.server


DEFAULT_APPROVAL_POLICY = '''# Default approval policy using canonical imports (no magic names)
from adgn.agent.approvals import PolicyDecision, WellKnownServers, WellKnownTools, ApprovalContext

def decide(ctx):
    """Return (PolicyDecision, rationale:str) for clarity.

    - Always ALLOW UI communication tools
    - Always ALLOW approval_policy management ops
    - Always ALLOW all resource operations
    - Default to ASK for everything else
    """
    server = ctx.server
    tool = ctx.tool

    if server == WellKnownServers.UI and tool in (WellKnownTools.SEND_MESSAGE, WellKnownTools.END_TURN):
        return (PolicyDecision.ALLOW, "UI communication")

    if server == WellKnownServers.APPROVAL_POLICY and tool in (WellKnownTools.GET_STATUS, WellKnownTools.PROPOSE, WellKnownTools.WITHDRAW):
        return (PolicyDecision.ALLOW, "Approval management")

    if server == WellKnownServers.RESOURCES:
        return (PolicyDecision.ALLOW, "Resource operations allowed")

    if server == WellKnownServers.APPROVAL_POLICY:
        return (PolicyDecision.ALLOW, "All approval_policy server ops allowed")

    return (PolicyDecision.ASK, "Default: ask for approval")

# Minimal self-checks for the default policy. Policies must define TEST_CASES
# as a list of (ApprovalContext, expected PolicyDecision) tuples.
TEST_CASES = [
    (
        ApprovalContext(
            server=WellKnownServers.UI,
            tool=WellKnownTools.SEND_MESSAGE,
            arguments={},
        ),
        PolicyDecision.ALLOW,
    ),
]
'''


class ApprovalPolicyEngine:
    """Holds editable policy source and a single open proposal (in memory).

    Loose coupling: agent can run without this engine; servers/clients may react
    to notifications via an optional notifier callback.
    """

    def __init__(self, notifier: Callable[[str], None] | None = None) -> None:
        self._policy_source: str = DEFAULT_APPROVAL_POLICY
        self._policy_version: int = 1  # Start at 1 since we have default content
        self._proposals: dict[str, Proposal] = {}
        self._open_id: str | None = None
        # Notifier receives a resource URI (e.g., "approval-policy://policy.py" or proposals/{id}.json)
        self._notify = notifier

    def set_notifier(self, notifier: Callable[[str], None]) -> None:
        """Install/replace the out-of-band notifier for resource changes.

        Contract: notifier(uri) is sync and non-blocking (may schedule async work).
        """
        self._notify = notifier

    # --- Policy ---
    def get_policy(self) -> tuple[str, int]:
        return self._policy_source, self._policy_version

    def set_policy(self, source: str) -> int:
        # Validate policy is valid Python and tests pass before applying
        validate_policy_python(source)
        env = self._make_policy_globals()
        exec(source, env)
        self._run_tests(env)
        self._policy_source = source
        self._policy_version += 1
        if self._notify:
            self._notify("approval-policy://policy.py")
        return self._policy_version

    # Internal load used on startup to hydrate content/version from persistence
    def load_policy(self, source: str, *, version: int) -> None:
        # Validate tests when hydrating from persistence
        env = self._make_policy_globals()
        exec(source, env)
        self._run_tests(env)
        self._policy_source = source
        self._policy_version = version

    def load_proposals(self, proposals: list[Proposal]) -> None:
        """Hydrate proposals from persistence without emitting notifications.

        If multiple 'open' proposals exist, the last one by created_at becomes open.
        """
        self._proposals = {p.id: p for p in proposals}
        # Pick the most recent open, if any
        open_ids = [p.id for p in proposals if p.status == "open"]
        self._open_id = open_ids[-1] if open_ids else None

    def _make_policy_globals(self) -> dict[str, Any]:
        """Return a safe globals dict for policy exec with curated builtins and whitelisted symbols.

        Policy authoring expectations (documented in the UI and tests):
        - Policies must import all symbols explicitly, including:
          ApprovalContext, PolicyDecision, WellKnownServers, WellKnownTools.
        - Policies must import any stdlib or seatbelt symbols explicitly.
        - Imports are restricted to a curated allowlist to keep execution safe.
        """
        safe_builtin_names = (
            "None",
            "True",
            "False",
            "len",
            "any",
            "all",
            "sum",
            "min",
            "max",
            "sorted",
            "map",
            "filter",
            "enumerate",
            "zip",
            "set",
            "list",
            "dict",
            "tuple",
            "range",
            "isinstance",
            "issubclass",
            "str",
            "int",
            "float",
            "bool",
            "abs",
            "round",
        )
        safe_builtins: dict[str, Any] = {
            name: getattr(_builtins, name)
            for name in safe_builtin_names
            if hasattr(_builtins, name)
        }
        # Do not pre-bind stdlib modules; require explicit imports in policy code
        # Restricted import hook
        allowed_modules = {
            "adgn.agent.approvals",
            "adgn.seatbelt.model",
            # Allow standard URL parsing in policies
            "urllib",
            "urllib.parse",
            # Allow limited filesystem path utilities in policies when needed
            "os",
            "pathlib",
            # Allow getopt for simple arg parsing in policies/tests
            "getopt",
            # Allow curated stdlib modules; policy must import explicitly
            "re",
            "json",
            "fnmatch",
            "math",
            "datetime",
            "ipaddress",
        }

        def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            # Resolve absolute module name when relative imports attempted
            name.split(".")[0]
            if level and globals and globals.get("__name__"):
                # Disallow relative imports in policies
                raise ImportError("relative imports are not allowed in approval policy")
            # Allow submodules of whitelisted modules
            ok = name in allowed_modules or any(
                name.startswith(mod + ".") for mod in allowed_modules
            )
            if not ok:
                raise ImportError(f"import not allowed: {name}")
            return __import__(name, globals, locals, fromlist, level)

        safe_builtins_with_import = dict(safe_builtins)
        safe_builtins_with_import["__import__"] = _safe_import

        env: dict[str, Any] = {"__builtins__": safe_builtins_with_import}

        return env

    def _run_tests(self, env: dict[str, Any]) -> None:
        fn = env.get("decide")
        if not callable(fn):
            raise ValueError("policy missing decide(ctx) function")
        tests = env.get("TEST_CASES")
        if not isinstance(tests, (list, tuple)) or len(tests) < 1:
            raise ValueError("policy must define TEST_CASES with at least one test")
        for idx, tc in enumerate(tests):
            if not (isinstance(tc, (list, tuple)) and len(tc) == 2):
                raise ValueError(f"TEST_CASES[{idx}] must be a 2-tuple (ctx, expected)")
            ctx, expected = tc
            if not isinstance(ctx, ApprovalContext):
                raise ValueError(f"TEST_CASES[{idx}]: ctx must be ApprovalContext")
            if not isinstance(expected, PolicyDecision):
                raise ValueError(f"TEST_CASES[{idx}]: expected must be PolicyDecision enum")
            out = fn(ctx)
            # Enforce strict return format: (PolicyDecision, rationale:str)
            if not (isinstance(out, (tuple, list)) and len(out) == 2):
                raise ValueError(
                    f"TEST_CASES[{idx}]: decide() must return a 2-tuple (PolicyDecision, rationale:str)"
                )
            decision_val, rationale_val = out[0], out[1]
            if not isinstance(decision_val, PolicyDecision):
                raise ValueError(
                    f"TEST_CASES[{idx}]: first element of decide() return must be PolicyDecision enum"
                )
            if not isinstance(rationale_val, str):
                raise ValueError(
                    f"TEST_CASES[{idx}]: second element of decide() return must be str rationale"
                )
            if decision_val != expected:
                raise ValueError(
                    f"TEST_CASES[{idx}] failed: expected {expected.value}, got {decision_val.value}"
                )

    def decide_with_info(self, ctx: "ApprovalContext") -> tuple[str, str | None]:
        """Evaluate policy; returns one of: allow|deny_continue|deny_abort|ask.

        Executes the current policy if present, otherwise returns ("ask", None).
        """
        src = (self._policy_source or "").strip()
        if not src:
            logger.debug("ApprovalPolicyEngine.decide: no policy source, returning 'ask'")
            return ("ask", None)
        # Context must be an ApprovalContext (no dict backcompat)
        ctx_obj = ctx

        # Execute policy in a curated sandbox: safe builtins + safe stdlib modules
        env = self._make_policy_globals()
        try:
            exec(src, env)
            fn = env.get("decide")
            if callable(fn):
                # Provide an object with attribute access; also supports dict-like .get
                out = fn(ctx_obj)
                logger.debug(
                    "ApprovalPolicyEngine.decide: server=%s tool=%s result=%s",
                    ctx_obj.server,
                    ctx_obj.tool,
                    out,
                )
                # Enforce strict outputs: (PolicyDecision, rationale:str)
                if not (isinstance(out, (tuple, list)) and len(out) == 2):
                    raise ValueError(
                        "Policy decide(ctx) must return a 2-tuple (PolicyDecision, rationale:str)"
                    )
                decision_val, rationale_val = out[0], out[1]
                if not isinstance(decision_val, PolicyDecision):
                    raise ValueError("Policy decide(ctx) first element must be PolicyDecision enum")
                if not isinstance(rationale_val, str):
                    raise ValueError("Policy decide(ctx) second element must be a str rationale")
                return (decision_val.value, rationale_val)
        except Exception:
            # Fail fast so tests surface policy errors instead of hanging in ask-mode
            raise
        return ("ask", None)

    def decide(self, ctx: "ApprovalContext") -> str:
        """Compatibility wrapper returning only the decision string."""
        d, _ = self.decide_with_info(ctx)
        return d

    # --- Proposals ---
    def create_proposal(
        self, source: str, rationale: str | None = None, *, proposal_id: str | None = None
    ) -> str:
        """Create a new open proposal for a policy change and return its id.

        If proposal_id is provided (e.g., by a server wanting sequential IDs), it is used as-is.
        Otherwise a random id is generated.
        """
        validate_policy_python(source)
        if self._open_id is not None:
            raise RuntimeError("a proposal is already open")
        pid = proposal_id or f"p-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        self._proposals[pid] = Proposal(
            id=pid, source=source, status="open", created_at=now, rationale=rationale
        )
        self._open_id = pid
        if self._notify:
            self._notify(f"approval-policy://proposals/{pid}.json")
        return pid

    def withdraw(self, pid: str) -> None:
        p = self._proposals.get(pid)
        if not p:
            return
        if p.status == "open":
            p.status = "withdrawn"
            p.decided_at = datetime.now(timezone.utc)
            if self._open_id == pid:
                self._open_id = None
            if self._notify:
                self._notify(f"approval-policy://proposals/{pid}.json")

    def apply(self, pid: str, decision: Literal["approve", "reject"]) -> None:
        p = self._proposals.get(pid)
        if not p:
            raise KeyError(pid)
        if p.status != "open":
            return
        now = datetime.now(timezone.utc)
        if decision == "reject":
            p.status = "rejected"
            p.decided_at = now
            if self._open_id == pid:
                self._open_id = None
            if self._notify:
                self._notify(f"approval-policy://proposals/{pid}.json")
            return

        # decision == "approve": attempt to apply; on failure, mark rejected and raise ValueError
        try:
            # Validate + run tests; set_policy increments version and notifies policy.py
            self.set_policy(p.source)
        except Exception as e:
            # Reject the proposal on any failure during apply
            p.status = "rejected"
            p.decided_at = now
            if self._open_id == pid:
                self._open_id = None
            if self._notify:
                self._notify(f"approval-policy://proposals/{pid}.json")
            raise ValueError(f"Policy approval failed: {e}") from e
        else:
            # Successful apply → mark proposal approved and notify
            p.status = "approved"
            p.decided_at = now
            if self._open_id == pid:
                self._open_id = None
            if self._notify:
                self._notify(f"approval-policy://proposals/{pid}.json")

    def get_status(self) -> ApprovalStatus:
        proposals = [ProposalMeta.model_validate(p) for p in self._proposals.values()]
        return ApprovalStatus(
            version=self._policy_version,
            open_proposal=self._open_id,
            proposals=proposals,
        )

    # Proposal getters (server constructs resource URIs; engine provides data only)
    def get_proposal(self, pid: str) -> ProposalSnapshot:
        p = self._proposals.get(pid)
        if not p:
            raise KeyError(pid)
        return ProposalSnapshot.model_validate(p)


class ApprovalContext:
    """Context object passed to approval policy with attribute and dict-like access.

    Attributes:
      - server: MCP server name (e.g., "docker", "resources")
      - tool: MCP tool name (e.g., "exec", "read")
      - arguments: dict of tool arguments (validated upstream)

    Convenience:
      - args alias to arguments
      - get(key, default) and __getitem__ for limited dict-compat
    """

    __slots__ = ("server", "tool", "arguments")

    def __init__(
        self,
        *,
        server: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> None:
        self.server = server
        self.tool = tool
        self.arguments = arguments

    # Friendly alias
    @property
    def args(self) -> dict[str, Any]:
        return self.arguments

    # Dict-like helpers for backwards compatibility with policies using ctx.get
    def get(self, key: str, default: Any = None) -> Any:
        if key == "server":
            return self.server
        if key == "tool":
            return self.tool
        if key in {"arguments", "args"}:
            return self.arguments
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key, None)
        if val is None and key not in {"server", "tool", "arguments", "args"}:
            raise KeyError(key)
        return val

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"ApprovalContext(server={self.server!r}, tool={self.tool!r}, "
            f"arguments={self.arguments!r})"
        )
        # (Engine handles proposals; context has no proposal API.)


# ---- Agent handler for approvals (before_tool_call) ----
class ApprovalPolicyHandler(BaseHandler):
    """Agent handler that enforces approval policy at the agent boundary.

    Evaluates ApprovalPolicyEngine and, when needed, gates the tool call via an
    ApprovalHub rendezvous. Returns a BeforeToolCallDecision:
    - ContinueDecision → proceed with MCP tool execution
    - AbortTurnDecision → abort the turn
    - BypassToolInjectOutput → inject provided CallToolResult instead of calling MCP
    """

    def __init__(
        self,
        engine: ApprovalPolicyEngine | None,
        hub: ApprovalHub,
    ) -> None:
        self._engine = engine
        self._hub = hub
        self._recorder: Callable[[str, str, ApprovalOutcome], Awaitable[None]] | None = None
        self._get_run_id: Callable[[], str | None] | None = None
        self._pending_notifier: Callable[[str, str, str | None], Awaitable[None]] | None = None
        # Handler requires a live ApprovalHub to gate ask-mode decisions
        if self._hub is None:
            raise ValueError("ApprovalPolicyHandler requires a non-None ApprovalHub")

    def set_policy_outcome_recorder(
        self,
        recorder: Callable[[str, str, ApprovalOutcome], Awaitable[None]],
        get_run_id: Callable[[], str | None] | None = None,
    ) -> None:
        """Install a recorder for policy outcomes.

        recorder is called with (call_id, tool_key, outcome) where outcome is one of
        policy_allow | policy_deny_continue | policy_deny_abort. get_run_id can be used
        by the recorder to associate outcomes with the active run.
        """
        self._recorder = recorder
        self._get_run_id = get_run_id

    def set_pending_notifier(
        self, notifier: Callable[[str, str, str | None], Awaitable[None]]
    ) -> None:
        """Install a notifier to emit 'approval_pending' to UIs when gating.

        Called with (call_id, tool_key, args_json) immediately after the request
        is registered and before awaiting a decision.
        """
        self._pending_notifier = notifier

    async def before_tool_call(self, evt: ToolCall) -> BeforeToolCallDecision:
        # If no engine configured, pass through
        if not self._engine:
            return ContinueDecision()

        # Build policy context from the tool call; arguments remain opaque JSON
        try:
            server, tool = parse_mcp_function(evt.name)
        except Exception:
            # If name isn't namespaced (shouldn't happen), allow by default
            return ContinueDecision()
        ctx = ApprovalContext(
            server=server,
            tool=tool,
            arguments=json.loads(evt.args_json or "{}"),
        )

        mode, rationale = self._engine.decide_with_info(ctx)
        logger.debug(
            "ApprovalPolicyHandler decision: server=%s tool=%s mode=%s",
            server,
            tool,
            mode,
        )
        tool_key = build_mcp_function(server, tool)
        if mode == "allow":
            if self._recorder is not None:
                await self._recorder(evt.call_id, tool_key, ApprovalOutcome.POLICY_ALLOW)
            return ContinueDecision()
        if mode == "deny_abort":
            if self._recorder is not None:
                await self._recorder(evt.call_id, tool_key, ApprovalOutcome.POLICY_DENY_ABORT)
            return AbortTurnDecision(reason="policy_denied")
        if mode == "deny_continue":
            if self._recorder is not None:
                await self._recorder(evt.call_id, tool_key, ApprovalOutcome.POLICY_DENY_CONTINUE)
            # Build informative error message with rationale when provided
            err_msg = f"policy denied: {server}.{tool}"
            if rationale:
                err_msg = f"{err_msg} ({rationale})"
            return BypassToolInjectOutput(
                result=mcp_types.CallToolResult(
                    content=[],
                    isError=True,
                    structuredContent={
                        "ok": False,
                        "error": err_msg,
                        "rationale": rationale,
                    },
                )
            )

        # ask: require hub for gating; if none, pass through
        if not self._hub:
            return ContinueDecision()

        # Use the real model-provided call_id to keep flows consistent end-to-end
        call_id = evt.call_id
        req = ApprovalRequest(
            tool_key=tool_key,
            tool_call=ApprovalToolCall(
                name=tool,
                call_id=call_id,
                args_json=json.dumps(ctx.arguments, ensure_ascii=False),
            ),
        )
        # Register the request and notify UIs before awaiting resolution
        decision_coro = self._hub.await_decision(call_id, req)
        if self._pending_notifier is not None:
            # Do not swallow exceptions: propagate to surface programming errors
            await self._pending_notifier(call_id, tool_key, evt.args_json)
        decision = await decision_coro
        return decision
