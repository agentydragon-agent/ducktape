# TypeScript Types Analysis

## Overview

This document analyzes the TypeScript types in the web frontend, comparing generated types from Pydantic models with manually-defined shared types.

## Generated Types (`src/generated/types.ts`)

**Source**: Auto-generated from Python Pydantic models using `scripts/generate_types.py`

**Purpose**: Provide TypeScript interfaces that match the backend API data structures

**Generation command**: `npm run generate-types` (runs before build via `prebuild` hook)

### Key Types

#### Agent Types
- `AgentInfo` - Complete agent information including capabilities, mode, and resource URIs
- `AgentMode` - Enum: `'local' | 'bridge'`
- `AgentList` - List of agents
- `Capabilities` - Key-value map of agent capabilities

#### Approval System Types
- `PendingApproval` - Tool call awaiting approval
  - Fields: `call_id`, `tool`, `args`, `timestamp`
- `ApprovalHistoryEntry` - Single approval decision in timeline
  - Fields: `call_id`, `tool`, `args`, `outcome`, `reason?`, `timestamp`
- `ApprovalOutcome` - Enum with 6 variants:
  - Policy decisions: `policy_allow`, `policy_deny_continue`, `policy_deny_abort`
  - User decisions: `user_approve`, `user_deny_continue`, `user_deny_abort`
- `ApprovalRequest` - Tool call approval request
- `AgentApprovalsPending` - Pending approvals for an agent
- `AgentApprovalsHistory` - Approval history for an agent

#### Tool Call Types
- `ToolCall` - Basic tool call info (name, call_id, args_json)
- `Decision` - Decision about a tool call (outcome, decided_at, reason?)
- `ToolCallExecution` - Execution result (completed_at, output)
- `ToolCallRecord` - Complete tool call lifecycle record
  - States: PENDING (no decision/execution), EXECUTING (decision but no execution), COMPLETED (both)

#### Policy Types
- `PolicyProposalInfo` - Metadata for a policy proposal
  - Fields: `id`, `status`, `created_at`, `decided_at?`, `proposal_uri`
- `AgentPolicyProposals` - List of policy proposals for an agent

#### Tool Action Types
- `ApproveToolCallArgs` - Arguments for approve_tool_call tool
- `RejectToolCallArgs` - Arguments for reject_tool_call tool
- `AbortAgentArgs` - Arguments for abort_agent tool

#### Content Types (MCP-style)
- `CallToolResult` - Server response to a tool call
- `TextContent`, `ImageContent`, `AudioContent` - Different content types
- `ResourceLink`, `EmbeddedResource` - Resource representations
- `TextResourceContents`, `BlobResourceContents` - Resource content variants

#### Other Types
- `RunStatus` - Enum: `'running' | 'finished' | 'error' | 'aborted'`
- `EventType` - Enum for various event types (user_text, assistant_text, tool_call, etc.)

## Manually-Defined Types (`src/shared/types.ts`)

**Source**: Hand-written TypeScript

**Purpose**: Frontend-specific types for UI state, WebSocket payloads, and data structures not directly mapped to backend models

### Key Types

#### Agent Management Types
- `AgentRow` - Simplified agent data for lists
  - Fields: `id`, `created_at?`, `live?`, `working?`, `last_updated?`, `metadata`, `lifecycle?`
- `AgentListResponse` - Response from agent list API
- `AgentStatus` - Comprehensive agent status including lifecycle, run phase, policy, UI, MCP, container states
  - More detailed than `AgentInfo` from generated types

#### UI State Types
- `UiState` - UI display state (seq, items)
- `UiDisplayItem` - Union of display items:
  - `UserMessageItem`, `AssistantMarkdownItem`, `EndTurnItem`, `ToolItem`
- `ExecContent`, `JsonContent`, `ToolContent` - Tool execution content types

#### MCP Types
- `McpTool` - MCP tool definition (name, description, inputSchema)
- `McpServerState` - Enum: `'initializing' | 'running' | 'failed'`
- `McpState` - MCP server state entries
- `ServerEntry` - Union of server entry variants:
  - `ServerEntryInitializing`, `ServerEntryRunning`, `ServerEntryFailed`
- `InitializeView` - MCP initialization view
- `SamplingSnapshot` - Snapshot of MCP servers

#### Policy Types
- `PolicyState` - Simple policy state (id?)
- `PolicyError` - Policy parsing/validation error
- `PolicyErrorCode` - Enum: `'read_error' | 'parse_error'`
- `Proposal` - **SIMPLIFIED VERSION** (id, status?)
  - Compare with `PolicyProposalInfo` from generated types (more complete)
- `ApprovalPolicyInfo` - **DIFFERENT FROM GENERATED**
  - Fields: `content`, `id` (number), `proposals?` (Proposal[])
  - Not the same as generated `AgentPolicyProposals`

#### Approval Types
- `ApprovalKind` - **SIMPLIFIED VERSION**: `'approve' | 'deny_continue' | 'deny_abort'`
  - Compare with `ApprovalOutcome` from generated types (distinguishes policy vs user)

#### WebSocket Payload Types
- `IncomingPayload` - Union of all possible incoming WebSocket message types
- `SnapshotPayload`, `UiStateSnapshotPayload`, `UiStateUpdatedPayload`
- `RunStatusPayload`, `ApprovalPendingPayload`, `ApprovalDecisionPayload`
- `AcceptedPayload`, `ErrorPayload`

#### Other Types
- `ContainerState` - Container presence/ID/ephemeral status
- `DeleteResponse` - API delete response
- `ServerResourcesCaps` - MCP resource capabilities

## Potential Duplicates and Overlaps

### 1. Approval Outcome Types

**Generated**: `ApprovalOutcome` (6 variants distinguishing policy vs user)
```typescript
type ApprovalOutcome =
  | "policy_allow"
  | "policy_deny_continue"
  | "policy_deny_abort"
  | "user_approve"
  | "user_deny_continue"
  | "user_deny_abort"
```

**Shared**: `ApprovalKind` (3 variants, simplified)
```typescript
type ApprovalKind = 'approve' | 'deny_continue' | 'deny_abort'
```

**Analysis**: These serve different purposes:
- `ApprovalOutcome`: Backend representation distinguishing policy vs user decisions
- `ApprovalKind`: Frontend representation for UI interactions

**Recommendation**: Keep both for now. Consider mapping between them where needed.

### 2. Policy Proposal Types

**Generated**: `PolicyProposalInfo` (complete backend model)
```typescript
interface PolicyProposalInfo {
  id: Id;
  status: Status;
  created_at: CreatedAt;
  decided_at?: DecidedAt1;
  proposal_uri: ProposalUri;
}
```

**Shared**: `Proposal` (simplified frontend model)
```typescript
type Proposal = {
  id: string
  status?: 'pending' | 'approved' | 'rejected'
}
```

**Analysis**: The shared `Proposal` type is used within `ApprovalPolicyInfo` and by UI components. It's a simplified view of the backend `PolicyProposalInfo`.

**Recommendation**:
- **Short-term**: Keep both. The simplified version is sufficient for current UI needs.
- **Long-term**: Consider migrating to `PolicyProposalInfo` from generated types for consistency with backend.

### 3. Agent Information Types

**Generated**: `AgentInfo` (backend model)
```typescript
interface AgentInfo {
  agent_id: AgentId1;
  capabilities: Capabilities;
  mode: AgentMode;
  state_uri?: StateUri;
  approvals_uri?: ApprovalsUri;
  policy_proposals_uri?: PolicyProposalsUri;
}
```

**Shared**: `AgentRow`, `AgentStatus` (frontend models)
- `AgentRow`: Simplified for agent lists
- `AgentStatus`: Comprehensive runtime status including UI/MCP/container states

**Analysis**: These serve different purposes:
- `AgentInfo`: Static agent configuration and capabilities
- `AgentRow`/`AgentStatus`: Dynamic runtime state and UI-specific data

**Recommendation**: Keep all three. They represent different aspects of an agent.

## Current Usage

### Generated Types
- **Not yet imported** by any UI components
- Verified to compile correctly (see `src/generated/types.test.ts`)
- Available for use but not yet integrated

### Shared Types
- **Actively used** throughout the codebase
- Imported by:
  - `components/ApprovalsPanel.svelte`
  - `components/AgentsSidebar.svelte`
  - `components/ChatPane.svelte`
  - `components/ServersPanel.svelte`
  - `features/agents/api.ts`
  - `features/agents/stores.ts`
  - `features/chat/stores_channels.ts`
  - And others

## Migration Strategy

### Phase 1: Import Generated Types (Current)
- [x] Generated types file created and verified
- [x] Test file demonstrating usage created
- [x] Types compile without errors

### Phase 2: Identify Integration Points (Recommended Next Steps)
1. **API Response Handling**: Where backend responses are parsed
   - `features/agents/api.ts` - API calls should use generated types for responses
   - Example: `/agents` endpoint should return `AgentList` type

2. **WebSocket Message Handlers**: Where backend messages are processed
   - `features/chat/stores_channels.ts` - Message handlers could use generated types
   - Need to map backend payloads to generated types

3. **Component Props**: Where components receive backend data
   - Components should accept generated types where applicable
   - Example: Approval panels could use `PendingApproval[]` from generated types

### Phase 3: Gradual Migration (Future)
1. Start with API layer - ensure fetch/response use generated types
2. Update stores to use generated types internally
3. Update component props to accept generated types
4. Add type guards/mappers where needed to convert between shared and generated types
5. Deprecate duplicate shared types once migration is complete

## Type Categories

### Generated Only (Backend-driven)
- Tool call lifecycle types (`ToolCall`, `Decision`, `ToolCallExecution`, `ToolCallRecord`)
- Content types (`TextContent`, `ImageContent`, `CallToolResult`)
- Tool action arguments (`ApproveToolCallArgs`, `RejectToolCallArgs`, `AbortAgentArgs`)

### Shared Only (Frontend-specific)
- UI state types (`UiState`, `UiDisplayItem`, etc.)
- WebSocket payload types (`IncomingPayload` union)
- Runtime state types (`AgentStatus`, `ContainerState`)
- MCP server types (`McpTool`, `ServerEntry`, `InitializeView`)

### Overlapping (Different representations)
- Approval outcomes: `ApprovalOutcome` (generated) vs `ApprovalKind` (shared)
- Policy proposals: `PolicyProposalInfo` (generated) vs `Proposal` (shared)
- Agent info: `AgentInfo` (generated) vs `AgentRow`/`AgentStatus` (shared)

## Recommendations

1. **Keep both type files** - They serve complementary purposes
   - Generated types: Backend contract
   - Shared types: Frontend-specific data structures

2. **Start using generated types in API layer**
   - Import from `generated/types` in `features/agents/api.ts`
   - Type responses properly using generated types
   - Add type guards where needed

3. **Add type mapping utilities**
   - Create mappers between generated and shared types where needed
   - Example: `approvalOutcomeToKind()`, `proposalInfoToProposal()`

4. **Document type usage in code**
   - Add comments explaining when to use each type
   - Update component prop types to use generated types where appropriate

5. **Future: Consider consolidation**
   - Once generated types are fully integrated, evaluate which shared types can be removed
   - Prefer generated types for anything that directly maps to backend models
   - Keep shared types only for truly frontend-specific concerns

## Testing

Generated types are verified with comprehensive tests in `src/generated/types.test.ts`:
- Object construction
- Type safety enforcement
- Enum validation
- Optional fields handling
- Complex nested structures
- All tests passing (18/18)
