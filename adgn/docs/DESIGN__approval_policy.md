# Approval Policy — Summary

This document summarizes what’s implemented and what remains for the approval policy subsystem.

Implemented

- Approval engine (adgn/agent/approvals.py)
  - ApprovalPolicyEngine with decide(ctx), set_policy(), create_proposal(), withdraw(), apply(), get_status().
  - ApprovalContext passed to policy with attributes: server, tool, arguments.
  - Syntax validation via ast.parse; invalid policies raise ValueError.
  - Default policy: allow UI and approval_policy ops; ask otherwise.

- Agent gating (handler-based)
  - ApprovalPolicyHandler consults the engine and gates tool calls before MCP execution, coordinating ask/deny via ApprovalHub.
  - MiniCodex.create can inject the handler when provided approval_engine and approval_hub.

- MCP server (adgn/mcp/approval_policy/server.py)
  - Resources: approval-policy://policy.py and approval-policy://proposals/{id}.json.
  - Tools: propose, withdraw, get_status (apply is UI-only via engine.apply()).
  - Notifies on policy/proposal changes.

- Notifications to LLM
  - NotificationsHandler injects a concise system message with resource version deltas; approval_policy updates surface here.

- Tests
  - Engine lifecycle and MCP server smoke tests; end-to-end approval flows covered by agent/UI tests. Full test suite passes.

Remaining (optional follow-ups)

- Resource read gating: extend policy/handler to gate read_resource calls if desired (currently allowed).
- Policy sandboxing: execute user policy under a restricted environment.
- Persistence/versioning: write policy/proposals to disk with history.
- Multi-user/editor UX: conflict prevention, richer notices.

Usage (high level)

- Create engine and hub; inject into agent:
  - engine = ApprovalPolicyEngine(); hub = ApprovalHub()
  - await MiniCodex.create(..., approval_engine=engine, approval_hub=hub)

- Optionally expose approval_policy MCP server using ApprovalPolicyServer(engine) for LLM visibility and proposals.

