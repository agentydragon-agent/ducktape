local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    status_shared.py AgentStatusCore duplicates data available via the 2-layer
    compositor. Three fields (mcp: McpState lines 76-78, policy: PolicyState lines
    66-68, pending_approvals: int line 91) wrap compositor resources without adding
    behavior.

    Impact: Type indirection (must access .entries for data), manual state tracking
    instead of querying compositor, sync risks between custom status and MCP
    resources, redundant APIs.

    These fields map to MCP resources: mcp → resources://compositor/servers,
    policy → resources://approval-policy/policy.py, pending_approvals →
    len(resources://approval-policy/pending).

    Remove the three redundant fields from AgentStatusCore. Clients should query
    MCP resources directly for server state, policy, and pending approvals.

    Benefits: Single source of truth (MCP resources authoritative), automatic updates
    via resource subscriptions, consistent interface, simpler status model containing
    only non-MCP state.

    Principle: Don't duplicate MCP-available data in custom APIs. Let clients use
    standard MCP protocol to avoid sync issues.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/status_shared.py': [
      [66, 68],   // PolicyState thin wrapper
      [76, 78],   // McpState thin wrapper
      [91, 91],   // pending_approvals redundant field
    ],
  },
)
