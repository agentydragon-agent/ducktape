# Parallel Execution Plan: Phases 0-5

## Overview

This document maps out the complete parallel execution strategy for implementing the MCP-based Management UI, from Phase 0 (foundation) through Phase 5 (cleanup).

**Total estimated time with parallelism**: ~7-9 days (vs ~17-20 days sequential)

## Execution Waves

### PHASE 0: Type Consolidation & Data Models (4-6 hours)

#### Wave 0.1 (2 parallel agents)
```
Agent 0.1.A: Rename ApprovalToolCall → ToolCall
Agent 0.1.B: Define persistence models (Decision, ToolCallExecution, ToolCallRecord)
```

#### Wave 0.2 (3 parallel agents)
**Depends on**: Wave 0.1 complete
```
Agent 0.2.C: Update database schema (needs 0.1.B)
Agent 0.2.D: Fix middleware bugs (needs 0.1.A)
Agent 0.2.V1: Verify Task A (needs 0.1.A)
```

#### Wave 0.3 (4 parallel agents)
**Depends on**: Wave 0.2 complete
```
Agent 0.3.E: Track execution in middleware (needs 0.1.A, 0.1.B, 0.2.C, 0.2.D)
Agent 0.3.V2: Verify Task B (needs 0.1.B)
Agent 0.3.V3: Verify Task C (needs 0.2.C)
Agent 0.3.V4: Verify Task D (needs 0.2.D)
```

#### Wave 0.4 (2 parallel agents)
**Depends on**: Wave 0.3 complete
```
Agent 0.4.V5: Verify Task E (needs 0.3.E)
Agent 0.4.V-final: Integration verification (needs all 0.1-0.3)
```

#### Wave 0.5 (Code quality scans - parallel)
**Depends on**: Wave 0.4 complete
```
Agent 0.5.Q1: Scan for getattr/hasattr/setattr usage
Agent 0.5.Q2: Scan for Any types
Agent 0.5.Q3: Scan for code smells (prompts/scans/*.md)
Agent 0.5.Q4: Run mypy type checking
Agent 0.5.Q5: Check code coverage ≥80%
```

---

### PHASE 1: Backend (3-4 days)

#### Wave 1.1 (4 parallel agents)
**Depends on**: Phase 0 complete
```
Agent 1.1.A: Infrastructure Registry Enhancement
  - Add known_agents() method
  - Add get_infrastructure() method
  - Add get_agent_mode() method
  - Add get_local_runtime() method
  - Tests: multiple agents, mode detection, routing

Agent 1.1.B: Token Authentication
  - UITokenAuthMiddleware implementation
  - generate_ui_token() from env or random
  - Token validation logic
  - Tests: valid/invalid/missing tokens

Agent 1.1.C: Agent State Models
  - PendingApproval model
  - ApprovalHistoryEntry model
  - AgentInfo model
  - All response models for resources
  - Tests: Pydantic validation, serialization

Agent 1.1.D: Approval Engine Integration
  - get_pending() → list[PendingApproval]
  - get_history() → list[ApprovalHistoryEntry]
  - Update persistence to use ToolCallRecord
  - Tests: pending/history retrieval
```

#### Wave 1.2 (3 parallel agents)
**Depends on**: Wave 1.1 complete
```
Agent 1.2.A: Agents Server - Resources (Part 1)
  - resource://agents/list
  - resource://agents/{id}/state
  - resource://agents/{id}/approvals/pending
  - Uses models from 1.1.C, routing from 1.1.A
  - Tests: resource reads, routing, error handling

Agent 1.2.B: Agents Server - Resources (Part 2)
  - resource://agents/{id}/approvals/history
  - resource://approvals/pending (global mailbox)
  - Multi-content-block ReadResourceResult
  - Tests: history timeline, global mailbox format

Agent 1.2.C: Agents Server - Tools
  - approve_tool_call(agent_id, call_id)
  - reject_tool_call(agent_id, call_id, reason)
  - abort_agent(agent_id)
  - Tests: tool routing, error handling, local vs bridge
```

#### Wave 1.3 (2 parallel agents)
**Depends on**: Wave 1.2 complete
```
Agent 1.3.A: Resource Notifications
  - Wire up approval engine listeners
  - Wire up agent state listeners
  - broadcast_resource_updated() calls
  - Tests: notifications fire correctly

Agent 1.3.B: CLI Integration
  - Update CLI to create agents server
  - Print Management UI URL with token
  - Server startup integration
  - Tests: CLI output, server startup
```

#### Wave 1.4 (Verification - 3 parallel agents)
**Depends on**: Wave 1.3 complete
```
Agent 1.4.V1: Backend Integration Tests
  - Multi-agent scenarios
  - Approval flow end-to-end
  - Resource subscriptions

Agent 1.4.V2: Code Quality Scans
  - No getattr/hasattr/setattr
  - No Any types
  - Type checking passes

Agent 1.4.V3: API Contract Verification
  - All resources return correct Pydantic models
  - All tools have proper signatures
  - Global mailbox returns TextResourceContents
```

---

### PHASE 2: Frontend (2-3 days)

**Note**: Can start Wave 2.1 once Wave 1.2 completes (basic resources available)

#### Wave 2.1 (3 parallel agents)
**Depends on**: Wave 1.2.A complete (basic resources)
```
Agent 2.1.A: Install & Configure MCP SDK
  - npm install @modelcontextprotocol/sdk
  - MCP client utilities (createMCPClient)
  - Streamable HTTP transport
  - Tests: client connection

Agent 2.1.B: Token Management
  - getTokenFromURL()
  - getTokenFromStorage()
  - saveTokenToStorage()
  - handleAuthFailure()
  - Tests: token extraction, storage

Agent 2.1.C: Base UI Structure
  - App.svelte skeleton
  - Loading/error states
  - Route structure
  - Tests: component rendering
```

#### Wave 2.2 (3 parallel agents)
**Depends on**: Wave 2.1 complete, Wave 1.2.B complete (history resource)
```
Agent 2.2.A: Agents Client (Core)
  - connectAgents()
  - agentList store
  - refreshAgentList()
  - Resource subscriptions
  - Tests: connection, list fetch, subscriptions

Agent 2.2.B: Agents Client (Approvals)
  - globalApprovals store
  - refreshGlobalApprovals()
  - approveToolCall(), rejectToolCall()
  - getAgentHistory()
  - Tests: approval operations, history fetch

Agent 2.2.C: Agents Client (Agent Ops)
  - abortAgent()
  - Agent state subscriptions
  - Notification handling
  - Tests: abort, state updates
```

#### Wave 2.3 (4 parallel agents)
**Depends on**: Wave 2.2 complete
```
Agent 2.3.A: Agent List Component
  - Sidebar with agent list
  - State badges (color-coded)
  - Agent selection
  - Tests: rendering, state badges

Agent 2.3.B: Timeline Component
  - Tool call timeline display
  - Merge policy gate + UI blocks
  - Chronological ordering
  - Tests: timeline rendering, merging

Agent 2.3.C: Approvals Component
  - Global approvals mailbox
  - Pending approval cards
  - Approve/Reject actions
  - Tests: approval UI, actions

Agent 2.3.D: Policy Editor Component
  - Policy source display
  - Uses existing policy server resources
  - Policy proposals display
  - Tests: policy display, proposals
```

#### Wave 2.4 (Verification - 2 parallel agents)
**Depends on**: Wave 2.3 complete
```
Agent 2.4.V1: Frontend Integration Tests
  - Full UI workflows
  - Real-time updates
  - Error handling

Agent 2.4.V2: Code Quality
  - TypeScript compilation
  - Linting
  - No console errors
```

---

### PHASE 3: Shared Models (1 day)

#### Wave 3.1 (2 parallel agents)
**Depends on**: Wave 1.2 complete (backend models stable)
```
Agent 3.1.A: Install & Configure Generator
  - npm install pydantic-to-typescript
  - Configure package.json scripts
  - Set up prebuild hook

Agent 3.1.B: Export Pydantic Models
  - Ensure all models in protocol.py
  - Export approval models
  - Export response models
  - Export tool input/output schemas
```

#### Wave 3.2 (2 parallel agents)
**Depends on**: Wave 3.1 complete
```
Agent 3.2.A: Generate Types
  - Run pydantic2ts
  - Verify generated types
  - Fix any generation issues

Agent 3.2.B: Update Frontend Imports
  - Replace manual types with generated
  - Update all component imports
  - Verify type compatibility
```

#### Wave 3.3 (Verification - 1 agent)
**Depends on**: Wave 3.2 complete
```
Agent 3.3.V1: Type Compatibility Verification
  - TypeScript compilation passes
  - Runtime type checks
  - API response validation
```

---

### PHASE 4: Testing (2-3 days)

**Note**: Different test suites can run in parallel once their dependencies are met

#### Wave 4.1 (4 parallel agents)
**Depends on**: Phases 1, 2, 3 complete
```
Agent 4.1.A: Backend Unit Tests
  - All backend components
  - Mock dependencies
  - Edge cases

Agent 4.1.B: Frontend Unit Tests
  - All UI components
  - Mock MCP client
  - User interactions

Agent 4.1.C: Integration Tests
  - Backend + Frontend
  - Multi-agent scenarios
  - Full approval workflows

Agent 4.1.D: Playwright E2E Tests (Part 1)
  - Management UI basic flows
  - Agent list navigation
  - Approval actions
```

#### Wave 4.2 (3 parallel agents)
**Depends on**: Wave 4.1 complete
```
Agent 4.2.A: Playwright E2E Tests (Part 2)
  - Real-time updates
  - Content blocks rendering
  - Error handling

Agent 4.2.B: Performance Tests
  - Multi-agent load
  - Resource notification performance
  - Frontend rendering performance

Agent 4.2.C: Security Tests
  - Token authentication
  - Authorization checks
  - Input validation
```

#### Wave 4.3 (Verification - 2 parallel agents)
**Depends on**: Wave 4.2 complete
```
Agent 4.3.V1: Test Coverage Analysis
  - Backend coverage ≥80%
  - Frontend coverage ≥80%
  - Integration coverage report

Agent 4.3.V2: Test Results Consolidation
  - All test suites pass
  - No flaky tests
  - Performance benchmarks met
```

---

### PHASE 5: Cleanup (1 day)

#### Wave 5.1 (3 parallel agents)
**Depends on**: All tests pass (Phase 4 complete)
```
Agent 5.1.A: Remove WebSocket Endpoints
  - Delete /ws/policy
  - Delete /ws/approvals
  - Delete /ws/mcp
  - Remove WebSocket test fixtures

Agent 5.1.B: Update Documentation
  - Architecture docs
  - API reference
  - Deployment guide
  - Migration guide

Agent 5.1.C: Code Cleanup
  - Remove dead code
  - Remove commented code
  - Remove debug logging
  - Clean up imports
```

#### Wave 5.2 (Verification - 1 agent)
**Depends on**: Wave 5.1 complete
```
Agent 5.2.V1: Final Verification
  - All tests still pass
  - No dead code
  - Documentation complete
  - No stub implementations
```

---

## Summary: Critical Path & Parallelism

### Critical Path (Sequential Dependencies)
```
Phase 0 (0.1-0.5) → Phase 1 (1.1-1.4) → Phase 3 (3.1-3.3) → Phase 4 (4.1-4.3) → Phase 5 (5.1-5.2)
                         ↓
                    Phase 2 (2.1-2.4) ────────────────────────┘
                    (starts after 1.2)
```

### Maximum Parallelism by Wave

| Wave | Parallel Agents | Duration Est. | Dependencies |
|------|----------------|---------------|--------------|
| 0.1 | 2 | 1 hour | None |
| 0.2 | 3 | 1 hour | 0.1 |
| 0.3 | 4 | 1 hour | 0.2 |
| 0.4 | 2 | 0.5 hour | 0.3 |
| 0.5 | 5 | 0.5 hour | 0.4 |
| **1.1** | **4** | **0.5 day** | **Phase 0** |
| 1.2 | 3 | 1 day | 1.1 |
| **2.1** | **3** | **0.5 day** | **1.2.A** (starts early!) |
| 1.3 | 2 | 0.5 day | 1.2 |
| 2.2 | 3 | 0.5 day | 2.1, 1.2.B |
| 1.4 | 3 | 0.5 day | 1.3 |
| 2.3 | 4 | 1 day | 2.2 |
| 2.4 | 2 | 0.5 day | 2.3 |
| **3.1** | **2** | **0.5 day** | **1.2** |
| 3.2 | 2 | 0.25 day | 3.1 |
| 3.3 | 1 | 0.25 day | 3.2 |
| **4.1** | **4** | **1 day** | **1-3** |
| 4.2 | 3 | 1 day | 4.1 |
| 4.3 | 2 | 0.5 day | 4.2 |
| 5.1 | 3 | 0.5 day | Phase 4 |
| 5.2 | 1 | 0.25 day | 5.1 |

### Timeline

**Sequential**: 17-20 days
**Parallel**: 7-9 days

**Speedup**: ~2.5x

### Resource Requirements

**Peak concurrency**: 5 agents (Wave 0.5, potentially Wave 4.1)
**Average concurrency**: 2-3 agents
**Total agents**: 87 agents across all waves

## Execution Strategy

1. **Phase 0**: Full autonomous execution (as discussed)
2. **Phase 1**: Can pause after Wave 1.2 for checkpoint
3. **Phase 2**: Starts early (overlaps with Phase 1)
4. **Phase 3**: Quick type generation pass
5. **Phase 4**: Comprehensive testing phase
6. **Phase 5**: Final cleanup and docs

## Next Steps

Ready to begin autonomous execution starting with Phase 0, Wave 0.1?
