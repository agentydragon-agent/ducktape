from __future__ import annotations

from typing import Any
from mcp.server.fastmcp.server import MCPResource
from urllib.parse import urlparse
import re

# Approval policy resource scheme and helpers
APPROVAL_SCHEME = "approval-policy"
POLICY_NAME = "policy.py"
PROPOSALS_HOST = "proposals"
PROPOSAL_SUFFIX = ".json"
PROPOSAL_PATH_RE = re.compile(rf"/([A-Za-z0-9_-]+){re.escape(PROPOSAL_SUFFIX)}$")
POLICY_URI = f"{APPROVAL_SCHEME}://{POLICY_NAME}"


def make_proposal_uri(pid: str) -> str:
    return f"{APPROVAL_SCHEME}://{PROPOSALS_HOST}/{pid}{PROPOSAL_SUFFIX}"


from adgn.llm.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.llm.mini_codex.approvals import ApprovalPolicyEngine


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
      - apply(proposal_id: str, decision: "approve"|"reject") -> { ok }
      - get_status() -> engine status dict

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
            instructions="Editable approval policy controlling auto-approvals",
        )
        self._engine = engine

        # Bridge engine notifications → MCP protocol resource updates
        def _notify(uri: str) -> None:
            # Fire-and-forget; schedule broadcast on the event loop
            import asyncio
            import logging

            logging.getLogger("adgn.mcp").debug("engine notify uri=%s", uri)
            task = asyncio.create_task(self.broadcast_resource_updated(uri))
            ApprovalPolicyServer._last_broadcast_task = task

        # Install notifier hook on the engine (required wiring)
        self._engine.set_notifier(_notify)

        # Tools
        @self.tool()
        async def propose(source: str, rationale: str | None = None) -> dict[str, Any]:  # type: ignore[valid-type]
            pid = self._engine.create_proposal(source=source, rationale=rationale)
            # Engine will trigger _notify(proposals/{id}.json)
            return {"proposal_id": pid}

        @self.tool()
        async def withdraw(proposal_id: str) -> dict[str, Any]:  # type: ignore[valid-type]
            self._engine.withdraw(proposal_id)
            return {"ok": True}

        @self.tool()
        async def apply(proposal_id: str, decision: str) -> dict[str, Any]:  # type: ignore[valid-type]
            if decision not in {"approve", "reject"}:
                return {"ok": False, "error": "invalid decision"}
            self._engine.apply(proposal_id, decision)
            # On approve, engine.set_policy() is called which will trigger _notify(policy.py)
            return {"ok": True}

        @self.tool()
        async def get_status() -> dict[str, Any]:  # type: ignore[valid-type]
            return self._engine.get_status()

    # ---- Resources (dynamic, backed by engine) ----
    async def list_resources(self) -> list[MCPResource]:  # type: ignore[override]
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
        for pr in status.get("proposals", []) or []:
            pid = pr.get("id")
            if isinstance(pid, str) and pid:
                resources.append(
                    MCPResource(
                        uri=make_proposal_uri(pid),
                        name=f"{pid}{PROPOSAL_SUFFIX}",
                        mimeType="application/json",
                    )
                )
        return resources

    async def read_resource(self, uri):  # type: ignore[override]
        # Conform to low-level server expectation: return str | bytes | Iterable[ReadResourceContents]
        u = str(uri)
        parsed = urlparse(u)
        if parsed.scheme != APPROVAL_SCHEME:
            raise KeyError(u)
        host = parsed.netloc
        path = parsed.path or ""
        if host == POLICY_NAME:
            source, _ver = self._engine.get_policy()
            return source  # low-level wraps into TextResourceContents with text/plain
        if host == PROPOSALS_HOST:
            m = PROPOSAL_PATH_RE.fullmatch(path)
            if not m:
                raise KeyError(u)
            pid = m.group(1)
            proposal = self._engine.get_proposal(pid)
            import json as _json

            return _json.dumps(proposal, ensure_ascii=False)
        raise KeyError(u)

    async def await_last_broadcast(self) -> None:
        t = ApprovalPolicyServer._last_broadcast_task
        if t is not None and not t.done():
            try:
                await t
            except Exception:
                pass
