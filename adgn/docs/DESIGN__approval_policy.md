# Approval Policy — Editable, MCP-Visible, and LLM-Proposable

Status: draft
Owner: mpokorny

## Goals
- Let users author a small Python policy that decides per-tool approvals: allow | deny_continue | deny_abort | ask
- Expose the current policy and proposal state as an MCP server (approval_policy) so the LLM can:
  - Read the policy (as a resource)
  - Propose a change (one live proposal max)
  - Withdraw a proposal prior to user action
- Let the user edit/approve/reject policy changes via the UI (textarea + buttons)
- Reflect approvals/rejections to the LLM as system messages on the next sampling phase (analogous to notifications)
- Integrate the policy into the existing approval flow without breaking invariants or introducing racey UX

Non-goals
- Sandboxed/secure Python execution in v1 (document constraints and TRUST-LOCAL; follow-ups to sandbox)
- Multi-user authorship or version history UI (simple single-author flow is fine)

## High-level flow
1) Tool call arrives → server consults the Approval Policy engine before emitting approval_pending:
   - policy returns allow → proceed immediately with ContinueDecision (no approval_pending)
   - deny_continue → return BypassToolInjectOutput with a structured error ("policy denied: …")
   - deny_abort → return AbortTurnDecision(reason="policy_denied")
   - ask → emit approval_pending + wait on ApprovalHub (unchanged)

2) Policy editing:
   - UI sidebar exposes a textarea with current Python source and a Save button.
   - Save (user edit) writes policy immediately and bumps the approval_policy resource version (MCP notification)
   - Proposals are initiated only via the approval_policy.propose MCP tool (typically by the agent on its own or when the user asks it to). A single open proposal exists at a time. The UI only displays an open proposal and offers Approve/Reject.

3) Notifications to the LLM:
   - Any policy change (user save or approved proposal) bumps the approval_policy resource version → NotificationsHandler already injects a one-line system message summarizing resource_versions.
   - Additionally: when a proposal is approved or rejected (user action), approval_policy server writes a short textual event into its own NOTICES stream; NotificationsHandler will include a compact system message line (e.g., "approval_policy: proposal p123 approved").

## Data model (server-internal)
- CurrentPolicy: { source: str, version: int, updated_at: ts }
- Proposal: { id: str, source: str, status: "open"|"approved"|"rejected"|"withdrawn", created_at, decided_at? }
- At most one Proposal where status == "open"

## MCP server: approval_policy
Name: approval_policy
Instructions: "Mutable approval policy controlling automatic decisions before tool approvals…"

Resources
- approval-policy://policy.py — text; current policy source (MIME text/plain)
- approval-policy://proposals/{id}.json — one JSON document per proposal, including full content and headers
  - Shape: { id, source, status: "open"|"approved"|"rejected"|"withdrawn", created_at, decided_at? }
  - Discovery: use the existing mcp__resources server (resources/list) filtered to server="approval_policy" and uri_prefix="approval_policy://proposals/". An explicit index file is optional, not required.

Tools
- propose(payload: { source: str, rationale?: str }) -> { kind: "Proposed", proposal_id: str }
  - Errors: { kind: "Err", code: "ALREADY_OPEN" } when an open proposal exists
- withdraw(payload: { proposal_id: str }) -> { kind: "Withdrawn" }
  - Only by LLM; no effect if already decided; idempotent
- apply(payload: { proposal_id: str, decision: "approve"|"reject" }) -> { kind: "Applied", proposal_id: str }
  - Typically invoked by the UI server on user action (not by the LLM)
- get_status() -> { kind: "Status", version: int, open_proposal?: { id, created_at } }

Resource notifications (v1 scope)
- We do not require ResourceListChanged notifications.
- On policy write (user save or proposal approved): emit ResourceUpdatedNotification for approval_policy://policy.py.
- Proposal lifecycle: optional — we may emit ResourceUpdatedNotification for approval_policy://proposals/{id}.json when its content/status changes, but the UI/LLM do not rely on list-changed.
- Dynamic resources: proposals/{id}.json are created/removed at runtime. We will serve them via list_resources/read_resource from an in‑memory registry; discovery can come from get_status or reading a known proposal URI; no list-changed dependency.

Structured notices
- Server keeps a small in-memory queue of notices (strings) with timestamps (e.g., "proposal p123 approved").
- Expose a transient resource approval_policy://notices.txt (tail, last N lines) to surface in NotificationsHandler’s summary when changed; or encode the notice inside the status SystemMessage (see below).

## Policy engine (evaluation)
- Function signature of user policy (in Python source):
  ```python
  # Required function
  def decide(ctx: dict) -> str:  # returns one of: "allow", "deny_continue", "deny_abort", "ask"
      # ctx example: {"server": "ui", "tool": "send_message", "tool_key": "mcp__ui__send_message", "arguments": {...}}
      ...
  ```
- Evaluation site: ConnectionManager.before_tool_call (server side) PRIOR to emitting approval_pending, querying ApprovalPolicyEngine if present.
- Execution model: import/exec the latest source into a dedicated module dict with a tiny builtins allowlist; no compiled-code cache (v1). Keep only the latest source string; execute fresh each decision. Follow-up: sandboxing.
- On exception: treat as "ask" and append a notice: "policy error: …" (we avoid auto-deny on policy exceptions in v1).

## Per-session state pattern (loose coupling)
- Scope: per-agent process only (same lifetime as the MiniCodex agent + its McpManager)
- Residency: single in-memory ApprovalPolicyEngine service independent of any MCP server
  - Holds CurrentPolicy and Proposal objects (no persistence in v1)
  - Provides a minimal typed API: get_policy(), set_policy(source), get_open_proposal(), create_proposal(source, rationale?), withdraw(id), apply(id, decision)
- Wiring/DI:
  - Create one ApprovalPolicyEngine per agent session and attach it to the backend runtime (e.g., app.state.approval_policy_engine)
  - ConnectionManager.before_tool_call consults the engine if present; if absent, default behavior (no auto-approval) continues unchanged
  - The approval_policy FastMCP server (optional) is a thin façade over the engine: it lists/reads dynamic resources from the engine and exposes propose/withdraw/apply/get_status tools by delegating to it
- Accessors:
  - UI backend endpoints call the engine directly (not via MCP)
  - Agent/LLM uses the approval_policy MCP server when enabled; otherwise, proposals are simply not available (tool not present)
- Notifications:
  - Prefer protocol ResourceUpdatedNotification via ServerSession.send_resource_updated for approval_policy://policy.py (and proposals optionally).
  - Optionally also call McpManager.notify_resource_updated as a fallback for agent-internal notices.

## Server integration (FastAPI UI backend)
- Add endpoints
  - GET /approval-policy → { source, version, open_proposal?: {...}, proposals: [...] } (reads from ApprovalPolicyEngine)
  - POST /approval-policy/save { source } → set_policy(source) on the engine; bump version; return new version (and send ResourceUpdatedNotification for policy.py)
  - POST /approval-policy/proposals/{id}/approve|reject → engine.apply(...)
- App state wiring
  - Store the ApprovalPolicyEngine on app.state and pass its notifier to McpManager for resource updates
  - If the approval_policy MCP server is enabled, construct it with a reference to the engine; otherwise, the agent still runs and approvals flow defaults to manual

## Frontend (Svelte UI)
- Sidebar panel: “Approval policy”
  - Textarea bound to policy source
  - Button: Save (persist edits). When a proposal is open, show Approve/Reject controls; no UI button to Propose or Revert (the agent uses the MCP tool for proposals).
  - Small status footer with version and last change timestamp
- WS behavior
  - No changes to UiState; rendering remains driven by UiState
  - Status bar (servers) already updates via NotificationsHandler; optionally parse the approval_policy resource_versions to display a small badge

## LLM interaction contracts
- Reading policy: if the approval_policy MCP server is enabled, LLM can list resources via mcp__resources.list (server="approval_policy") and read approval_policy://policy.py and approval_policy://proposals/{id}.json; otherwise, these tools/resources are absent
- Propose: Call tool approval_policy.propose, receive { proposal_id } (only when server is enabled)
- Withdraw: Call approval_policy.withdraw with that id before user acts; tool returns Withdrawn
- Constraints
  - At most one live proposal per LLM/session; enforce in engine
- Feedback to LLM
  - On policy changes, send ResourceUpdatedNotification for policy.py (protocol). Optionally also inject a concise system notice. We do not depend on ResourceListChanged.

## Security & safety (v1)
- TRUST-LOCAL: Policy runs in-process without hard sandboxing (documented). Follow-up to add seatbelt/limited builtins.
- Storage: in-memory only (no persistence). Later we can persist both approval policy and agent session state.
- Deny patterns should be conservative; we’ll ship a default policy that returns "ask" unless tool == ui:send_message ("allow") and disallow typical destructive commands (e.g., rm -rf) for demo.

## Acceptance criteria
- Users can view/edit the policy from the UI and changes take effect immediately for new tool calls
- Agent runs fine with or without the approval_policy MCP server (engine optional; server optional)
- LLM can read policy and successfully create/withdraw a single proposal when the server is enabled; user sees the proposal and can approve/reject it in the UI
- On approval, policy is updated; on rejection, policy remains unchanged
- LLM receives a system message on the next sampling reflecting the change (via NotificationsHandler)
- Policy decisions (allow/deny/ask) gate tool calls without surfacing spurious approval_pending events
- Tests cover: engine decisions and lifecycle, dynamic resources, UI save/approve flows, and optionality of the server (enabled/disabled)

## Milestones
1) Server-only MVP
   - Implement approval_policy MCP server (resources + tools; in-proc only)
   - Dynamic resources: proposals/{id}.json add/remove; list_resources/read_resource wired to in-memory registry
   - Wire policy engine into ConnectionManager.before_tool_call
   - Unit tests: decisions and lifecycle; verify protocol ResourceUpdatedNotification on policy.py update (and optional proposal updated) is sent and observable by a subscribing client or by our NotificationsHandler fallback
2) UI integration
   - Backend endpoints proxying to approval_policy MCP
   - Svelte sidebar + basic UX (Save; Approve/Reject when open proposal exists)
   - E2E in-proc test: edit policy → allow/deny behavior changes; proposals created by agent visible and actionable
3) LLM propose/withdraw
   - Tools + proposal limit enforcement
   - Notifications plumbing and tests
4) Follow-ups
   - Sandbox policy execution (seatbelt)
   - Persist policy to disk with checksum/versioning
   - Multi-user conflict prevention and richer notices

## Open questions
- Notification path: emit protocol ResourceUpdatedNotification (ServerSession.send_resource_updated) for policy.py in all transports; maintain McpManager.notify_resource_updated as a fallback.
- Exact URIs and shapes: confirm approval_policy://proposals/{id}.json schema fields; approval_policy://proposals/index.json is optional and not required by notifications.
- Decision site: prefer McpManagerWithApprovals + ToolPolicyFn(engine) vs ConnectionManager.before_tool_call. Current design picks the wrapper for loose coupling. OK?
- LLM feedback channel: NotificationsHandler-only (resource delta line) vs also emitting a concise approval_policy notice string. Prefer NotificationsHandler-only?
- Default policy source: ship a minimal allow ui.send_message; ask otherwise? Any other built-ins?
- UI: Save only; Approve/Reject when open proposal exists. Any additional guardrails (e.g., lint policy source)?

## Next steps (pending design sign-off)
- Define ApprovalPolicyEngine interface (signatures + errors) and minimal default policy text
- Add optional McpManagerWithApprovals wiring in agent construction behind a flag
- Scaffold approval_policy FastMCP façade (optional) that delegates to the engine and exposes dynamic resources
- Minimal tests: engine decisions; dynamic resources add/remove; notifications integration; agent runs with/without server/engine
