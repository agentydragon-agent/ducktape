# Autonomous Agent Design Notes

## Communication

- Should be able to talk to me via messengers like Telegram or Matrix

## Permissions

- Graduated, tweakable permissions (like the approval-gate MCP server we've been building)

## Current State (OpenClaw in devel)

OpenClaw is wired up in devel. Its exec tool only knows three modes:

- Sandbox by Docker
- Execution in gateway, unsandboxed
- Execution in node, unsandboxed

No graduated permission model — it's either fully sandboxed (Docker) or fully unsandboxed.

## Infrastructure

- Agent should have its own k8s namespace
- A bunch of tokens it can use autonomously
- Some services available only with approvals (e.g., Gmail: read often OK, write only with approval)

## OpenClaw Pros/Cons

### Good

- Good support for messengers

### Problems

- No native MCP support — they have an MCP skill but it involves running `mcporter` utility in their exec environment
- Approval workflow doesn't fit well:
  - Need to be able to resume the agent with a notification when approvals are resolved (granted or denied)
  - OpenClaw has wiring for system notifications, but they only get delivered on next heartbeat
  - Our plugin cannot trigger an OpenClaw heartbeat — that's not part of the plugin API
- This is a blocker for the permission-based workflow: the agent needs to be notified when a tool use that got blocked on approval is granted/denied, and the agent loop needs to be poked to continue running
