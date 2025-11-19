# Parallel Execution Plan - MCP Management UI Completion

## Overview

This plan covers:
1. **Implementation Waves (1-6)**: Complete remaining Phases 1-5
2. **Scan Wave (7)**: Run 28 code quality scans in parallel
3. **Violation Analysis (8)**: Gather and categorize all violations
4. **Cleanup Wave (9)**: Fix violations in ~5 parallel tasks by affected area

**Total Estimated Time**: ~32-40 hours (vs ~80-100 hours sequential)
**Speedup**: ~2.5-3x with maximum parallelization

---

## WAVE 1: Backend Polish + Setup (3 parallel agents)
**Duration**: ~2-3 hours
**Dependencies**: None

### Agent 1.1: Phase 1 - Implement Agent State
**Files**: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

**Tasks**:
- Remove NotImplementedError at line 240
- Get sampling snapshot from `local_runtime.session`
- Handle edge cases (agent not sampling, no session)
- Add tests for different agent states

**Deliverable**: `resource://agents/{id}/state` returns actual data

### Agent 1.2: Phase 3 - Setup Type Generation
**Files**: `adgn/src/adgn/agent/web/package.json`, `adgn/scripts/generate_types.py`

**Tasks**:
- Install `pydantic-to-typescript`
- Create Python script to extract Pydantic models
- Configure npm script `generate-types`
- Test run and verify output

**Deliverable**: Type generation tooling ready

### Agent 1.3: Phase 4 - Coverage Configuration
**Files**: `adgn/pyproject.toml`, `.coveragerc`

**Tasks**:
- Add coverage configuration to pyproject.toml
- Set threshold to 80%
- Configure report format
- Run coverage report to verify

**Deliverable**: Coverage reporting configured

---

## WAVE 2: Frontend Foundation (4 parallel agents)
**Duration**: ~3-4 hours
**Dependencies**: Wave 1 complete (needs type generation ready)

### Agent 2.1: Phase 2.1 - Install MCP SDK
**Files**: `adgn/src/adgn/agent/web/package.json`

**Tasks**:
- `npm install @modelcontextprotocol/sdk`
- Verify TypeScript types available
- Test import in dummy file

**Deliverable**: MCP SDK installed and importable

### Agent 2.2: Phase 2.2 - MCP Client Wrapper
**Files**: `adgn/src/adgn/agent/web/src/features/mcp/client.ts` (NEW)

**Tasks**:
- Create `createMCPClient(url, token)` function
- Setup StreamableHTTP transport
- Add Bearer token auth header
- Add connection error handling
- Write unit tests

**Deliverable**: MCP client wrapper with tests

### Agent 2.3: Phase 2.3 - Token Management
**Files**: `adgn/src/adgn/agent/web/src/shared/token.ts` (NEW)

**Tasks**:
- `extractTokenFromURL()` function
- `saveToken()` / `getToken()` / `clearToken()` functions
- localStorage integration
- Handle auth failures
- Write unit tests

**Deliverable**: Token management utilities with tests

### Agent 2.4: Phase 3.2 - Generate Types
**Files**: `adgn/scripts/generate_types.py`, `adgn/src/adgn/agent/web/src/generated/types.ts`

**Tasks**:
- Run type generation script
- Export all MCP models (AgentInfo, PendingApproval, etc.)
- Verify TypeScript compiles
- Update imports in existing code

**Deliverable**: Generated TypeScript types

---

## WAVE 3: Frontend Core Components (5 parallel agents)
**Duration**: ~4-5 hours
**Dependencies**: Wave 2 complete

### Agent 3.1: Phase 2.4 - Resource Subscriptions
**Files**: `adgn/src/adgn/agent/web/src/features/mcp/subscriptions.ts` (NEW)

**Tasks**:
- Subscribe to `resource://approvals/pending`
- Subscribe to `resource://agents/{id}/approvals/history`
- Handle `notifications/resources/updated`
- Implement resource refresh logic
- Write unit tests

**Deliverable**: Subscription system with tests

### Agent 3.2: Phase 2.5 - Agent List Component
**Files**: `adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte` (MODIFY)

**Tasks**:
- Replace WebSocket with MCP client
- Fetch `resource://agents/list`
- Display capabilities and mode badges
- Subscribe to updates
- Write component tests

**Deliverable**: MCP-based agent list

### Agent 3.3: Phase 2.6 - Global Approvals Mailbox
**Files**: `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte` (NEW)

**Tasks**:
- Fetch `resource://approvals/pending`
- Parse multiple `TextResourceContents` blocks
- Display all pending approvals
- Wire approve/reject buttons to MCP tools
- Group by agent
- Write component tests

**Deliverable**: Global mailbox component with tests

### Agent 3.4: Phase 2.7 - Timeline Component
**Files**: `adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte` (NEW)

**Tasks**:
- Fetch `resource://agents/{id}/approvals/history`
- Display chronological tool call timeline
- Show states (PENDING/EXECUTING/COMPLETED)
- Display decision methods and tool outputs
- Auto-update via subscriptions
- Write component tests

**Deliverable**: Timeline component with tests

### Agent 3.5: Phase 2.8 - Abort Button (MCP)
**Files**: `adgn/src/adgn/agent/web/src/components/ChatComposer.svelte` (MODIFY)

**Tasks**:
- Replace WebSocket abort with MCP tool call
- Call `abort_agent` tool
- Only show for LOCAL agents
- State-based enable/disable
- Write component tests

**Deliverable**: MCP-based abort button

---

## WAVE 4: Integration & Backend Tests (4 parallel agents)
**Duration**: ~3-4 hours
**Dependencies**: Wave 3 complete

### Agent 4.1: Phase 4.1 - Backend Test Gaps
**Files**: `adgn/tests/agent/mcp_bridge/test_agents_server.py` (MODIFY)

**Tasks**:
- Add test for `resource://agents/{id}/state`
- Add test for resource notifications
- Add multi-agent global mailbox test
- Add historical timeline mixed decisions test
- Verify all tests pass

**Deliverable**: Comprehensive backend tests

### Agent 4.2: Phase 4.2 - Frontend MCP Client Tests
**Files**: `adgn/src/adgn/agent/web/src/features/mcp/client.test.ts` (NEW)

**Tasks**:
- Test MCP client connection
- Test resource fetching
- Test tool calling
- Test subscription handling
- Test notification processing

**Deliverable**: MCP client tests

### Agent 4.3: Phase 4.3 - Frontend Component Tests
**Files**: `**/components/*.test.ts` (NEW)

**Tasks**:
- Test AgentsSidebar rendering and updates
- Test GlobalApprovalsList with mock data
- Test ApprovalTimeline rendering
- Test user interactions (clicks, approvals)
- Verify ≥80% coverage

**Deliverable**: Component test suite

### Agent 4.4: Phase 4.4 - Playwright E2E Tests
**Files**: `adgn/tests/agent/e2e/test_mcp_ui.py` (NEW)

**Tasks**:
- Write `test_mcp_approval_flow_with_notifications`
- Write `test_multi_agent_global_mailbox`
- Write `test_timeline_displays_historical_decisions`
- Verify real-time updates work
- All tests pass

**Deliverable**: E2E tests for MCP features

---

## WAVE 5: Cleanup (3 parallel agents)
**Duration**: ~3-4 hours
**Dependencies**: Wave 4 complete (all tests passing)

### Agent 5.1: Phase 5.1 - Remove WebSocket Endpoints
**Files**: `adgn/src/adgn/agent/server/` (MODIFY/DELETE)

**Tasks**:
- Delete `agents_ws.py`
- Delete `channels/` directory
- Delete `ws.py`
- Remove WebSocket routes from `app.py`
- Verify no imports broken
- All tests still pass

**Deliverable**: WebSocket code removed

### Agent 5.2: Phase 5.2 - Remove Dead Code
**Files**: Multiple

**Tasks**:
- Run `ruff check --select F401` (unused imports)
- Run `ruff check --select ERA001` (commented code)
- Remove all flagged issues
- Remove completed TODOs
- Clean up backwards-compat shims

**Deliverable**: No dead code

### Agent 5.3: Phase 5.3 - Update Documentation
**Files**: `README.md`, `AGENTS.md`, `plan.md`, `docs/MCP_ARCHITECTURE.md` (NEW)

**Tasks**:
- Update README architecture section
- Update AGENTS.md workflow
- Mark all plan.md checkboxes complete
- Create MCP_ARCHITECTURE.md
- Document resource structure, tools, notifications

**Deliverable**: Documentation complete

---

## WAVE 6: Final Integration Verification (1 agent)
**Duration**: ~1 hour
**Dependencies**: Wave 5 complete

### Agent 6.1: Full System Integration Test
**Tasks**:
- Run all unit tests
- Run all integration tests
- Run all e2e Playwright tests
- Verify coverage ≥80%
- Check for regressions
- Smoke test full user workflow
- Generate test report

**Deliverable**: Verified system working end-to-end

---

## WAVE 7: Code Quality Scans (28 parallel agents)
**Duration**: ~2-3 hours
**Dependencies**: Wave 6 complete

**Strategy**: Launch 28 agents in parallel, one per scan prompt file.

Each agent scans all implementation files in:
- `adgn/src/adgn/agent/mcp_bridge/`
- `adgn/src/adgn/agent/web/src/`
- `adgn/tests/agent/mcp_bridge/`
- `adgn/tests/agent/e2e/test_mcp_ui.py`

### Scan Agent Template
```
Agent 7.{N}: Scan with prompts/scans/{scan_name}.md

Prompt: "Run code quality scan using prompts/scans/{scan_name}.md on all files modified/created during Phase 1-5 implementation.

Files to scan:
- adgn/src/adgn/agent/mcp_bridge/servers/agents.py
- adgn/src/adgn/agent/web/src/features/mcp/*.ts
- adgn/src/adgn/agent/web/src/components/*.svelte
- adgn/tests/agent/mcp_bridge/test_agents_server.py
- adgn/tests/agent/e2e/test_mcp_ui.py

Report all violations found with:
- File path and line number
- Violation description
- Severity (critical/major/minor)
- Suggested fix

Format output as structured JSON."

Deliverable: {scan_name}_violations.json
```

### Scan Agent List (28 agents)

1. **Agent 7.1**: api-model-design.md
2. **Agent 7.2**: asyncio-antipatterns.md
3. **Agent 7.3**: denormalized-computed-fields.md
4. **Agent 7.4**: duplicated-test-code.md
5. **Agent 7.5**: fastmcp-documentation-patterns.md
6. **Agent 7.6**: functional-over-imperative.md
7. **Agent 7.7**: identifier-naming.md
8. **Agent 7.8**: library-type-misuse.md
9. **Agent 7.9**: manual-serde-needs-pydantic.md
10. **Agent 7.10**: methods-vs-freestanding.md
11. **Agent 7.11**: mypy-appeasing-code.md
12. **Agent 7.12**: overly-loose-typing.md
13. **Agent 7.13**: pydantic-antipatterns.md
14. **Agent 7.14**: pygit2-patterns.md
15. **Agent 7.15**: pytest-tmp-paths.md
16. **Agent 7.16**: stringly-typed.md
17. **Agent 7.17**: suspicious-defaults.md
18. **Agent 7.18**: suspicious-nullability.md
19. **Agent 7.19**: test-assertions.md
20. **Agent 7.20**: timestamp-naming.md
21. **Agent 7.21**: trivial-forwarder-methods.md
22. **Agent 7.22**: trivial-forwarders.md
23. **Agent 7.23**: type-ignore-suppressions.md
24. **Agent 7.24**: unnecessary-verbosity.md
25. **Agent 7.25**: useless-comments-and-docs.md
26. **Agent 7.26**: useless-documentation.md
27. **Agent 7.27**: useless-test-classes.md
28. **Agent 7.28**: walrus-get-pattern.md

**Deliverable**: 28 violation JSON files

---

## WAVE 8: Violation Analysis & Categorization (1 agent)
**Duration**: ~1 hour
**Dependencies**: Wave 7 complete

### Agent 8.1: Gather and Categorize Violations

**Input**: All 28 violation JSON files from Wave 7

**Tasks**:
1. Merge all violations into single list
2. Deduplicate violations (same file/line reported by multiple scans)
3. Categorize by affected area:
   - **Category A**: Backend MCP server (agents.py, server.py)
   - **Category B**: Frontend MCP client (client.ts, subscriptions.ts)
   - **Category C**: Frontend UI components (Svelte files)
   - **Category D**: Tests (backend + frontend)
   - **Category E**: Type definitions and utilities
4. Within each category, group by violation type
5. Assign priority (critical/major/minor)
6. Estimate fix effort per category
7. Create 5 parallel cleanup tasks (one per category)

**Output**: `VIOLATIONS_REPORT.md` with structure:
```markdown
# Code Quality Violations Report

## Summary
- Total violations: {count}
- Critical: {count}
- Major: {count}
- Minor: {count}

## Violations by Category

### Category A: Backend MCP Server ({count} violations)
**Affected files**: agents.py (12), server.py (8), auth.py (3)
**Estimated effort**: 2-3 hours
**Priority violations**:
1. [CRITICAL] suspicious-nullability: Missing null checks in agents.py:240
2. [MAJOR] asyncio-antipatterns: Blocking call in agents.py:315
...

### Category B: Frontend MCP Client ({count} violations)
...

## Cleanup Task Allocation

### Cleanup Task 1: Backend MCP Server
**Agent Assignment**: Agent 9.1
**Files**: agents.py, server.py, auth.py
**Violations**: 23 total (5 critical, 10 major, 8 minor)
**Estimated effort**: 2-3 hours

### Cleanup Task 2: Frontend MCP Client
...
```

**Deliverable**: VIOLATIONS_REPORT.md with 5 cleanup task definitions

---

## WAVE 9: Parallel Cleanup (5 agents)
**Duration**: ~3-5 hours
**Dependencies**: Wave 8 complete

**Strategy**: Non-overlapping file sets ensure no conflicts

### Agent 9.1: Cleanup Category A - Backend MCP Server
**Files**:
- `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`
- `adgn/src/adgn/agent/mcp_bridge/server.py`
- `adgn/src/adgn/agent/mcp_bridge/auth.py`

**Input**: VIOLATIONS_REPORT.md → Category A violations

**Tasks**:
- Fix all critical violations first
- Fix major violations
- Fix minor violations if time permits
- Run tests after each fix
- Verify no regressions

**Deliverable**: All Category A violations fixed

### Agent 9.2: Cleanup Category B - Frontend MCP Client
**Files**:
- `adgn/src/adgn/agent/web/src/features/mcp/client.ts`
- `adgn/src/adgn/agent/web/src/features/mcp/subscriptions.ts`
- `adgn/src/adgn/agent/web/src/shared/token.ts`

**Input**: VIOLATIONS_REPORT.md → Category B violations

**Tasks**: (same pattern)

**Deliverable**: All Category B violations fixed

### Agent 9.3: Cleanup Category C - Frontend UI Components
**Files**:
- `adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte`
- `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte`
- `adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte`
- `adgn/src/adgn/agent/web/src/components/ChatComposer.svelte`

**Input**: VIOLATIONS_REPORT.md → Category C violations

**Tasks**: (same pattern)

**Deliverable**: All Category C violations fixed

### Agent 9.4: Cleanup Category D - Tests
**Files**:
- `adgn/tests/agent/mcp_bridge/test_agents_server.py`
- `adgn/src/adgn/agent/web/src/features/mcp/client.test.ts`
- `adgn/src/adgn/agent/web/src/components/*.test.ts`
- `adgn/tests/agent/e2e/test_mcp_ui.py`

**Input**: VIOLATIONS_REPORT.md → Category D violations

**Tasks**: (same pattern)

**Deliverable**: All Category D violations fixed

### Agent 9.5: Cleanup Category E - Types & Utilities
**Files**:
- `adgn/scripts/generate_types.py`
- `adgn/src/adgn/agent/web/src/generated/types.ts`
- `adgn/src/adgn/agent/types.py`
- `adgn/src/adgn/agent/persist/__init__.py`

**Input**: VIOLATIONS_REPORT.md → Category E violations

**Tasks**: (same pattern)

**Deliverable**: All Category E violations fixed

---

## WAVE 10: Final Verification (1 agent)
**Duration**: ~30 minutes
**Dependencies**: Wave 9 complete

### Agent 10.1: Final Smoke Test & Sign-off

**Tasks**:
1. Run all tests (unit, integration, e2e)
2. Verify coverage ≥80%
3. Run all 28 code quality scans again
4. Verify zero violations remain
5. Smoke test full user workflow:
   - Start server
   - Open UI with token
   - Create agent
   - Attach MCP server
   - Send prompt requiring approval
   - Verify notification arrives
   - Approve via UI
   - Verify timeline updates
   - Check multi-agent mailbox
6. Generate final report

**Deliverable**: Sign-off report with all checks passed

---

## Execution Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXECUTION TIMELINE                           │
└─────────────────────────────────────────────────────────────────────┘

Wave 1 (3 agents, 3h)    ████████
Wave 2 (4 agents, 4h)    ████████████
Wave 3 (5 agents, 5h)    ███████████████
Wave 4 (4 agents, 4h)    ████████████
Wave 5 (3 agents, 4h)    ████████████
Wave 6 (1 agent, 1h)     ███
Wave 7 (28 agents, 3h)   █████████
Wave 8 (1 agent, 1h)     ███
Wave 9 (5 agents, 5h)    ███████████████
Wave 10 (1 agent, 0.5h)  ██
                         └─────────────────────────────────────────┘
                         0h    10h    20h    30h    40h

Total Duration: ~30.5 hours
Max Concurrent Agents: 28 (Wave 7)
Total Agent Tasks: 59
```

## Dependency Graph

```
Wave 1 (Backend + Setup)
  ├─→ Wave 2 (Frontend Foundation)
  │     ├─→ Wave 3 (Frontend Components)
  │     │     ├─→ Wave 4 (Testing)
  │     │     │     ├─→ Wave 5 (Cleanup)
  │     │     │     │     ├─→ Wave 6 (Integration)
  │     │     │     │     │     ├─→ Wave 7 (Scans)
  │     │     │     │     │     │     ├─→ Wave 8 (Analysis)
  │     │     │     │     │     │     │     ├─→ Wave 9 (Cleanup)
  │     │     │     │     │     │     │     │     └─→ Wave 10 (Final)
```

## Critical Path

**Longest sequential path**: 30.5 hours
- Wave 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

**If run sequentially**: ~80-100 hours
**Speedup with parallelization**: ~2.6x

---

## Checkpoints

After each wave, verify:
- [ ] All agents completed successfully
- [ ] No merge conflicts
- [ ] All tests pass
- [ ] No regressions introduced

**Stop conditions** (abort if encountered):
- Any critical test failure
- More than 10% test coverage drop
- Breaking changes to public APIs
- Unresolvable merge conflicts

---

## Resource Requirements

**Human oversight required**:
- Wave 5 (WebSocket removal) - review before deletion
- Wave 8 (violation categorization) - review category assignments
- Wave 10 (final sign-off) - review before declaring complete

**Estimated human time**: ~2-3 hours review across all waves
