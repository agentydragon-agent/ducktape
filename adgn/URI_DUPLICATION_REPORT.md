# URI Duplication Analysis Report

**Repository**: ducktape/adgn
**Scan Date**: November 19, 2025
**Scope**: `/home/user/ducktape/adgn/src/adgn`

---

## Executive Summary

The codebase exhibits several patterns of URI definition duplication and inconsistent usage:

1. **Policies URIs defined locally** in approval_policy server instead of shared constants
2. **Mixed URI usage patterns** between shared constants, helper functions, and hardcoded strings
3. **Inconsistent format** for dynamic URI templates (format strings vs helper functions)

---

## Critical Findings

### 1. POLICIES_LIST_URI and policy_detail_uri — Local Definition (Should be in constants)

**Severity**: HIGH
**Category**: Duplication/Architecture

#### Definition Location
- **File**: `/home/user/ducktape/adgn/src/adgn/mcp/approval_policy/server.py`
- **Lines**: 33-38

```python
33  POLICIES_LIST_URI = "resource://policies/list"
34
35
36  def policy_detail_uri(policy_id: str) -> str:
37      """Resource URI for a specific policy proposal."""
38      return f"resource://policies/{policy_id}"
```

#### Problem
- These URI definitions are **private to the approval_policy server module**
- They **duplicate the architectural pattern** used in shared constants (see below)
- No other code can reference them without importing from this module
- They should be in `/home/user/ducktape/adgn/src/adgn/mcp/_shared/constants.py` for reuse

#### Usage in Same Module
- **Line 219**: `@self.resource(POLICIES_LIST_URI, ...)`
- **Line 232**: `@self.resource(policy_detail_uri("{policy_id}"), ...)`
- **Line 387, 400-401, 409-410**: Multiple calls to `notify_resource()` using these URIs

```python
# Line 387
self._engine.notify_resource(POLICIES_LIST_URI)

# Line 400
self._engine.notify_resource(policy_detail_uri(input.id))
```

#### Recommendation
**MOVE to shared constants** — These should be defined in `/home/user/ducktape/adgn/src/adgn/mcp/_shared/constants.py`:

```python
# Should add to constants.py:
POLICIES_LIST_URI: Final[str] = "resource://policies/list"
POLICIES_DETAIL_URI_FMT: Final[str] = "resource://policies/{policy_id}"

# And create a helper function in resources.py OR keep as local helper
def policies_detail(policy_id: str) -> str:
    """Resource URI for a specific policy."""
    return POLICIES_DETAIL_URI_FMT.format(policy_id=policy_id)
```

---

### 2. Hardcoded URIs in agents.py — Inconsistent Use of Helper Functions

**Severity**: MEDIUM
**Category**: Inconsistency

#### Overview
The `agents.py` file contains multiple hardcoded resource URIs that should use either the shared constants or the `resources` module helpers. The `resources` module was specifically designed to provide centralized URI generation (see `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/resources.py`), but it's underutilized.

#### Finding 1: Hardcoded Literal in Resource Definition (Line 229)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
228  @server.resource(
229      "resource://agents/list",
230      name="agents.list",
231      mime_type="application/json",
232      description="List all agents with capabilities and state",
233  )
```

**Status**: Inline string in decorator
**Should Use**: `resources.AGENTS_LIST` constant

**Current Definition in resources.py (line 4)**:
```python
4  AGENTS_LIST = "resource://agents/list"
```

**Fix**: Replace inline string with constant import

---

#### Finding 2: Hardcoded F-Strings for Agent State URI (Lines 244, 261)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

**Line 244** (in list_agents function):
```python
244          state_uri = f"resource://agents/{agent_id}/state" if is_local else None
```

**Line 261** (in resource decorator):
```python
260  @server.resource(
261      "resource://agents/{agent_id}/state",
262      name="agent.state",
263      mime_type="application/json",
264      description="Sampling state for a local agent",
265  )
```

**Status**: Hardcoded f-string on line 244; template string in decorator on line 261
**Should Use**: Helper function from `resources` module

**Current Definition in resources.py (lines 15-17)**:
```python
15  def agent_state(agent_id: str) -> str:
16      """Resource URI for agent sampling state."""
17      return f"resource://agents/{agent_id}/state"
```

**Fix**:
```python
# Line 244 should be:
state_uri = resources.agent_state(agent_id) if is_local else None
```

---

#### Finding 3: Hardcoded F-String for Approvals Pending (Line 245)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
245          approvals_uri = f"resource://agents/{agent_id}/approvals/pending"
```

**Status**: Hardcoded f-string
**Should Use**: `resources.agent_approvals_pending()` helper

**Current Definition in resources.py (lines 25-27)**:
```python
25  def agent_approvals_pending(agent_id: str) -> str:
26      """Resource URI for pending approvals for an agent."""
27      return f"resource://agents/{agent_id}/approvals/pending"
```

**Fix**:
```python
approvals_uri = resources.agent_approvals_pending(agent_id)
```

---

#### Finding 4: Hardcoded F-String for Policy Proposals (Line 246)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
246          policy_proposals_uri = f"resource://agents/{agent_id}/policy/proposals"
```

**Status**: Hardcoded f-string
**Should Use**: `resources.agent_policy_proposals()` helper

**Current Definition in resources.py (lines 40-42)**:
```python
40  def agent_policy_proposals(agent_id: str) -> str:
41      """Resource URI for policy proposals."""
42      return f"resource://agents/{agent_id}/policy/proposals"
```

**Fix**:
```python
policy_proposals_uri = resources.agent_policy_proposals(agent_id)
```

---

#### Finding 5: Hardcoded Global Approvals URI (Line 314)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
313  @server.resource(
314      "resource://approvals/pending",
315      name="approvals.pending.global",
316      mime_type="application/json",
317      description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)",
318  )
```

**Status**: Hardcoded string in decorator
**Should Use**: Shared constant `APPROVALS_PENDING_URI`

**Current Definition in constants.py (line 51)**:
```python
51  APPROVALS_PENDING_URI: Final[str] = "resource://approvals/pending"
```

**Current Definition in resources.py (line 7)**:
```python
7  APPROVALS_PENDING_GLOBAL = "resource://approvals/pending"
```

**Issue**: Same URI defined in **three places** (constants.py, resources.py, and hardcoded in agents.py)

**Fix**: Use the import already present:
```python
from adgn.agent.mcp_bridge import resources
# Then use:
@server.resource(
    resources.APPROVALS_PENDING_GLOBAL,
    ...
)
```

---

#### Finding 6: Hardcoded F-String for Agent Approval Details (Line 331)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
331                approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
```

**Status**: Hardcoded f-string
**Should Use**: `resources.agent_approval()` helper

**Current Definition in resources.py (lines 35-37)**:
```python
35  def agent_approval(agent_id: str, call_id: str) -> str:
36      """Resource URI for a specific approval."""
37      return f"resource://agents/{agent_id}/approvals/{call_id}"
```

**Fix**:
```python
approval_uri = resources.agent_approval(agent_id, approval.call_id)
```

---

#### Finding 7: Hardcoded Policy Proposal URI (Line 394)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
394                proposal_uri=f"resource://approval-policy/proposals/{p.id}",
```

**Status**: Hardcoded f-string
**Should Use**: `resources.policy_proposal()` helper

**Current Definition in resources.py (lines 45-47)**:
```python
45  def policy_proposal(proposal_id: str) -> str:
46      """Resource URI for a specific policy proposal."""
47      return f"resource://approval-policy/proposals/{proposal_id}"
```

**Fix**:
```python
proposal_uri=resources.policy_proposal(p.id),
```

---

#### Finding 8: Hardcoded Active Policy URI (Line 400)

**File**: `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
400            active_policy_uri="resource://approval-policy/policy.py"
```

**Status**: Hardcoded string
**Should Use**: Shared constant `APPROVAL_POLICY_RESOURCE_URI`

**Current Definition in constants.py (line 47)**:
```python
47  APPROVAL_POLICY_RESOURCE_URI: Final[str] = "resource://approval-policy/policy.py"
```

**Current Definition in resources.py (line 10)**:
```python
10  ACTIVE_POLICY = "resource://approval-policy/policy.py"
```

**Issue**: Same URI defined in **three places** (constants.py, resources.py, and hardcoded in agents.py)

**Fix**: Use the import already present:
```python
from adgn.agent.mcp_bridge import resources
# Then use:
active_policy_uri=resources.ACTIVE_POLICY,
```

---

## Architectural Pattern Analysis

### Current State: Three Layers of URI Definition

| Layer | File | Purpose | Status |
|-------|------|---------|--------|
| **1. Shared Constants** | `mcp/_shared/constants.py` | Single source of truth for all constants | Exists but **underutilized** |
| **2. Bridge Resources** | `agent/mcp_bridge/resources.py` | Helper functions for agent/approval URIs | Exists but **underutilized** in agents.py |
| **3. Local Definitions** | `mcp/approval_policy/server.py` | Policies URIs (should not be here) | **Problematic duplication** |
| **4. Hardcoded Strings** | `agent/mcp_bridge/servers/agents.py` | Inline URI definitions (should use layer 1-2) | **Inconsistent** |

### Best Practice from Shared Constants

The shared constants file establishes a pattern using `Final[str]` and format strings with placeholders:

```python
# From constants.py (correct pattern)
AGENTS_LIST_URI: Final[str] = "resource://agents/list"
AGENTS_STATE_URI_FMT: Final[str] = "resource://agents/{agent_id}/state"
AGENTS_APPROVALS_PENDING_URI_FMT: Final[str] = "resource://agents/{agent_id}/approvals/pending"

# Policies URIs currently violate this pattern (defined locally):
POLICIES_LIST_URI = "resource://policies/list"  # Missing Final[], in wrong file
# Missing POLICIES_DETAIL_URI_FMT altogether
```

---

## Recommendations Summary

### Priority 1: Move Policies URIs to Shared Constants

**Action**: Move lines 33-38 from `/home/user/ducktape/adgn/src/adgn/mcp/approval_policy/server.py` to `/home/user/ducktape/adgn/src/adgn/mcp/_shared/constants.py`

**Add to constants.py**:
```python
# Policy library resource URIs
POLICIES_LIST_URI: Final[str] = "resource://policies/list"
POLICIES_DETAIL_URI_FMT: Final[str] = "resource://policies/{policy_id}"
```

**Remove from server.py** (lines 33-38):
```python
POLICIES_LIST_URI = "resource://policies/list"

def policy_detail_uri(policy_id: str) -> str:
    """Resource URI for a specific policy proposal."""
    return f"resource://policies/{policy_id}"
```

**Update imports in server.py**:
```python
from adgn.mcp._shared.constants import (
    APPROVAL_POLICY_PROPOSALS_INDEX_URI,
    APPROVAL_POLICY_RESOURCE_URI,
    POLICIES_LIST_URI,
    POLICIES_DETAIL_URI_FMT,
    APPROVAL_POLICY_SERVER_NAME_APPROVER,
    APPROVAL_POLICY_SERVER_NAME_PROPOSER,
    APPROVAL_POLICY_SERVER_NAME_READER,
    RUNTIME_EXEC_TOOL_NAME,
    RUNTIME_SERVER_NAME,
)

# Helper function can stay or move to resources module
def policy_detail_uri(policy_id: str) -> str:
    """Resource URI for a specific policy proposal."""
    return POLICIES_DETAIL_URI_FMT.format(policy_id=policy_id)
```

---

### Priority 2: Use `resources` Module Helpers in agents.py

**Action**: Replace all hardcoded URIs in `agents.py` with calls to the `resources` module (already imported on line 21)

| Line(s) | Current | Replacement |
|---------|---------|-------------|
| 229 | `"resource://agents/list"` | `resources.AGENTS_LIST` |
| 244 | `f"resource://agents/{agent_id}/state"` | `resources.agent_state(agent_id)` |
| 245 | `f"resource://agents/{agent_id}/approvals/pending"` | `resources.agent_approvals_pending(agent_id)` |
| 246 | `f"resource://agents/{agent_id}/policy/proposals"` | `resources.agent_policy_proposals(agent_id)` |
| 314 | `"resource://approvals/pending"` | `resources.APPROVALS_PENDING_GLOBAL` |
| 331 | `f"resource://agents/{agent_id}/approvals/{approval.call_id}"` | `resources.agent_approval(agent_id, approval.call_id)` |
| 394 | `f"resource://approval-policy/proposals/{p.id}"` | `resources.policy_proposal(p.id)` |
| 400 | `"resource://approval-policy/policy.py"` | `resources.ACTIVE_POLICY` |

---

### Priority 3: Update resources.py to Include Policies URIs

**Action**: Add policy URIs to `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/resources.py`

```python
# Add these lines after existing definitions (line 48):

# Policy library resource URIs
POLICIES_LIST = "resource://policies/list"
"""Resource URI for listing all policies."""

def policies_detail(policy_id: str) -> str:
    """Resource URI for a specific policy."""
    return f"resource://policies/{policy_id}"
```

**Note**: This allows agents.py (or other code) to import policies URIs via the resources module for consistency, even though constants.py is the ultimate source of truth.

---

### Priority 4: Rationalize Constants vs. Helper Functions

**Decision**: Which approach to use for URI format strings?

**Option A** (Recommended for consistency):
- **constants.py**: Define all URI patterns as `Final[str]` with format placeholders
- **resources.py**: Provide helper functions that format the patterns

**Option B** (Current mixed approach):
- **constants.py**: Define both format strings and helper-ready patterns
- **resources.py**: Provide convenience functions; can import from constants or duplicate

**Recommended Action**: Adopt **Option A** for maximum clarity. Update constants.py:
- Format placeholders use `{agent_id}`, `{policy_id}`, `{call_id}`, etc.
- Provide helper in resources.py that calls `.format()`

Example:
```python
# constants.py
AGENTS_STATE_URI_FMT: Final[str] = "resource://agents/{agent_id}/state"

# resources.py
def agent_state(agent_id: str) -> str:
    from adgn.mcp._shared.constants import AGENTS_STATE_URI_FMT
    return AGENTS_STATE_URI_FMT.format(agent_id=agent_id)
```

---

## Files Requiring Changes

| File | Changes | Priority |
|------|---------|----------|
| `/home/user/ducktape/adgn/src/adgn/mcp/_shared/constants.py` | Add `POLICIES_LIST_URI` and `POLICIES_DETAIL_URI_FMT` | 1 |
| `/home/user/ducktape/adgn/src/adgn/mcp/approval_policy/server.py` | Remove local URI definitions; update imports | 1 |
| `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/resources.py` | Add policies URI helpers (optional but recommended) | 3 |
| `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py` | Replace 8 hardcoded URIs with helper calls | 2 |

---

## Testing & Validation

After implementing recommendations:

1. **Grep verification**: Ensure no new hardcoded `resource://` strings appear in `src/adgn/mcp/` and `src/adgn/agent/`
   ```bash
   grep -r 'f"resource://' adgn/src/ --include="*.py"
   grep -r '"resource://' adgn/src/ --include="*.py" | grep -v constants.py | grep -v resources.py
   ```

2. **Import verification**: Confirm all imports are satisfied
   ```bash
   direnv exec adgn python -c "from adgn.mcp._shared.constants import POLICIES_LIST_URI, POLICIES_DETAIL_URI_FMT"
   direnv exec adgn python -c "from adgn.agent.mcp_bridge import resources; print(resources.ACTIVE_POLICY)"
   ```

3. **Type checking**:
   ```bash
   direnv exec adgn mypy --config-file pyproject.toml src/adgn/mcp/ src/adgn/agent/mcp_bridge/
   ```

4. **Run affected tests**:
   ```bash
   direnv exec adgn pytest tests/mcp/ tests/agent/ -v
   ```

---

## Appendix: Full URI Pattern Reference

All resource URIs in the codebase (should be in constants.py):

| URI Pattern | File | Defined? | Notes |
|-------------|------|----------|-------|
| `resource://container.info` | constants.py:17 | Yes | Runtime container info |
| `resource://approval-policy/policy.py` | constants.py:47 | Yes | Active approval policy |
| `resource://approval-policy/proposals` | constants.py:48 | Yes | Policy proposals index |
| `resource://approval-policy/proposals/{id}` | resources.py:45-47 | Yes | Individual proposal |
| `resource://policies/list` | server.py:33 | No | **Should be in constants.py** |
| `resource://policies/{policy_id}` | server.py:36-38 | No | **Should be in constants.py** |
| `resource://approvals/pending` | constants.py:51 | Yes | Global pending approvals |
| `resource://agents/list` | constants.py:54 | Yes | All agents list |
| `resource://agents/{agent_id}/state` | constants.py:55 | Yes | Agent sampling state |
| `resource://agents/{agent_id}/snapshot` | constants.py:56 | Yes | Agent compositor snapshot |
| `resource://agents/{agent_id}/approvals/pending` | constants.py:57 | Yes | Agent pending approvals |
| `resource://agents/{agent_id}/approvals/{call_id}` | resources.py:35-37 | Yes | Specific approval |
| `resource://agents/{agent_id}/approvals/history` | constants.py:58 | Yes | Agent approval history |
| `resource://agents/{agent_id}/policy/proposals` | constants.py:59 | Yes | Agent policy proposals |
| `resource://agents/{agent_id}/info` | agents.py:404 | No | Not in constants (new URI) |
| `resource://compositor_meta/...` | constants.py:93-96 | Yes | Compositor metadata |
