"""HTTP MCP Bridge - exposes RunningInfrastructure to external agents.

This module provides an HTTP MCP server that external agents (ChatGPT, Claude.ai,
etc.) can connect to. It wraps RunningInfrastructure and provides:

- Token-based authentication (Bearer tokens → agent_id)
- Per-agent infrastructure isolation
- Policy-gated tool execution
- Optional UI for managing approvals/proposals

External agents connect via MCP over HTTP/SSE and get access to:
- Docker exec (via MCPConfig)
- Approval policy (read + propose changes)
- Compositor admin (live server reconfiguration, policy-gated)
- Resources (aggregated from all servers)

Not exposed to external agents:
- Loop control (local agents only)
- Chat servers (external agents maintain their own conversation state)
- UI server (optional, for human oversight only)
"""
