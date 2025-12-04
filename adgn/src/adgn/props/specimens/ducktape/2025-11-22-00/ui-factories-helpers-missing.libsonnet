local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    GlobalApprovalsList.svelte contains explicit tool/resource constructions at 6 locations instead
    of using factories/helpers with defaults: MCP client creation (line 69: createMCPClient with
    name/url/token), resource subscription (line 78: subscribeToResource with URI), resource reading
    (line 107: readResource with URI), approval parsing (lines 115-121: manual object construction
    with agent_id/tool_call/timestamp), approve tool call (lines 138-142: callTool with approve_tool_call
    and agent_id/call_id), reject tool call (lines 175-180: callTool with reject_tool_call and
    agent_id/call_id/reason).

    This creates verbose boilerplate (repeated patterns), no default values (must specify all parameters),
    hard to test (can't mock without recreating full objects), duplication (same patterns across component),
    and fragile (API changes require updating many call sites).

    Create factories/helpers: `createApprovalsClient(options?)` with default name/url/token,
    `fetchPendingApprovals(client)`, `approveToolCall(client, agentId, callId)`,
    `parseApprovalContents(contents)`. Provides default values, centralized logic, easier testing
    (mock helpers not raw calls), type safety, less duplication.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte': [
      [69, 71],    // Explicit MCP client creation
      [78, 78],    // Explicit resource subscription
      [107, 107],  // Explicit resource reading
      [115, 121],  // Explicit approval construction
      [138, 142],  // Explicit approve tool call
      [175, 180],  // Explicit reject tool call
    ],
  },
)
