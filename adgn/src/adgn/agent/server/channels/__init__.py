"""WebSocket channels - modular communication per component.

Each channel maps 1:1 to a backend component:
- session: LocalAgentRuntime.session (agent execution state)
- mcp: RunningInfrastructure.compositor (MCP servers)
- approvals: RunningInfrastructure.approval_hub (tool approvals)
- policy: RunningInfrastructure.approval_engine (approval policy)
- ui: AgentRuntime._ui_manager (UI state - optional)

Channels are independent, allowing clients to subscribe only to what they need.
Remote agents (external LLM providers) can use mcp/approvals/policy without session/ui.

Import from specific channel modules:
    from adgn.agent.server.channels.session import SessionChannelManager
    from adgn.agent.server.channels.mcp import McpChannelManager
    # etc.
"""
