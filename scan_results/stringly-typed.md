# Stringly-Typed Code Quality Scan Results

**Scan Date:** 2025-11-19
**Codebase:** ducktape repository
**Total Python Files Scanned:** 943
**Scan Based On:** `prompts/scans/stringly-typed.md`

---

## Executive Summary

The scan found **42 string fields** with categorical names that should be typed as enums instead of bare `str`, **36 Literal types** that could be converted to `StrEnum`, **81 string comparisons**, and **257 string assignments** to categorical fields. The codebase already defines **77 enum classes**, indicating good awareness of proper typing in some areas, but consistency is lacking.

### Key Findings Overview

| Category | Count | Files | Severity |
|----------|-------|-------|----------|
| String fields with categorical names | 42 | 24 | CRITICAL |
| Literal types (could be StrEnum) | 36 | 29 | HIGH |
| String comparisons with hardcoded strings | 81 | 37 | HIGH |
| String assignments to categorical fields | 257 | 109 | MEDIUM |
| Frequently-used string literals | 14 | - | MEDIUM |
| Existing enum definitions (good practice) | 77 | - | - |

### Impact Assessment

**Type Safety:** Without proper enum usage, many fields accept any string value at runtime, leading to potential bugs from typos and invalid values.

**Autocomplete:** IDE autocomplete cannot suggest valid values for bare `str` fields, unlike with enums.

**Refactoring:** Changing valid values requires searching for string literals throughout the codebase instead of using IDE rename tools.

**Serialization:** Pydantic and many SDKs handle StrEnum serialization correctly, maintaining backward compatibility with string-based APIs.

---

## Critical Findings: String Fields Without Enum Types

These fields should be typed as enums but are currently bare `str`:

### Pattern: Status Fields (4 violations)

```python
# ❌ BAD - adgn/src/adgn/agent/persist/__init__.py:72
class PolicyProposal(BaseModel):
    status: str  # Could be: pending, approved, denied, cancelled

# ❌ BAD - adgn/src/adgn/agent/mcp_bridge/servers/agents.py:179,213
class ServerState(BaseModel):
    status: str  # "running" or "stopped"
```

**Recommendation:** Create a `PolicyProposalStatus` enum:

```python
from enum import StrEnum

class PolicyProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"

class PolicyProposal(BaseModel):
    status: PolicyProposalStatus  # Type-safe!
```

### Pattern: State Fields (2 violations)

```python
# ❌ BAD - wt/src/wt/shared/github_models.py:92
class GitHubPRResponse(BaseModel):
    state: str  # "open", "closed", or "merged"
    # But PRState enum exists! (lines 48-51)

# ❌ BAD - wt/src/wt/shared/fixtures.py:15
state: str  # Pull request state
```

**Recommendation:** Use existing enums or create new ones:

```python
# ✓ GOOD - Use existing PRState enum
from wt.shared.github_models import PRState

class GitHubPRResponse(BaseModel):
    state: PRState  # Type-safe!
```

### Pattern: Type/Kind Fields (10 violations)

```python
# ❌ BAD - adgn/src/adgn/rspcache/events.py:14
type: str  # Event type not enumerated

# ❌ BAD - adgn/src/adgn/rspcache/admin_app.py:62
frame_type: str  # Frame type variants unclear

# ❌ BAD - claude/claude_optimizer/graders/scoresheet.py:65
request_type: str  # "code_generation" | "analysis" | "other"

# ❌ BAD - adgn/src/adgn/agent/transcript_handler.py:17
kind: str  # Message kind or similar
```

**Recommendation:** Use Literal or create StrEnum:

```python
from enum import StrEnum

# Option 1: Use Literal for small sets
from typing import Literal
request_type: Literal["code_generation", "analysis", "other"]

# Option 2: Use StrEnum for consistency and reusability
class RequestType(StrEnum):
    CODE_GENERATION = "code_generation"
    ANALYSIS = "analysis"
    OTHER = "other"

request_type: RequestType
```

### Pattern: Level Fields (2 violations)

```python
# ❌ BAD - llm/ducktape_llm_common/claude_linter_v2/config/clean_models.py:93
log_level: str = Field(default="INFO")

# ❌ BAD - gatelet/gatelet/server/config.py:51
log_level: str = Field(default="INFO")
```

**Recommendation:** Use standard enum:

```python
import logging

class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

log_level: LogLevel = Field(default=LogLevel.INFO)
```

---

## High Priority: Literal Types That Should Be StrEnum

29 files use `Literal` types, many with multiple string variants. These should be converted to `StrEnum` for better reusability and consistency:

### Examples of Literal Type Usage

**adgn/src/adgn/agent/server/protocol.py:**
```python
# Current: Multiple Literal types scattered
class MessageContent(BaseModel):
    role: Literal["user", "assistant", "system"]
    message_type: Literal["text", "tool_call", "error"]

# Better: Use StrEnum
class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class MessageType(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    ERROR = "error"

class MessageContent(BaseModel):
    role: Role
    message_type: MessageType
```

**Files with Literal types (29 total):**
- adgn/src/adgn/agent/handler.py
- adgn/src/adgn/agent/server/protocol.py
- adgn/src/adgn/openai_utils/model.py
- adgn/src/adgn/agent/models/policy_error.py
- adgn/src/adgn/agent/server/state.py
- adgn/src/adgn/agent/server/mcp_routing.py
- adgn/src/adgn/llm/sandboxer.py
- adgn/src/adgn/mcp/git_ro/server.py
- adgn/src/adgn/openai_utils/types.py
- adgn/src/adgn/props/cli_app/main.py
- adgn/src/adgn/props/eval_harness.py
- adgn/src/adgn/props/prompts/builder.py
- adgn/src/adgn/inop/engine/models.py
- adgn/src/adgn/inop/prompting/prompt_engineer.py
- adgn/src/adgn/llm/anthropic/types.py
- adgn/src/adgn/llm/sysrw/openai_typing.py
- adgn/src/adgn/agent/models/proposal_status.py
- adgn/src/adgn/agent/policies/policy_types.py
- adgn/src/adgn/git_commit_ai/cli.py
- llm/ducktape_llm_common/ducktape_llm_common/claude_code_api.py
- llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/checkers_v2.py
- llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/config/models.py
- llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/diff/parser.py
- llm/ducktape_llm_common/ducktape_llm_common/claude_linter/models.py
- llm/mcp/habitify/habitify_mcp_server/habitify_client.py
- llm/mcp/habitify/habitify_mcp_server/tools.py
- wt/src/wt/client/view_formatter.py
- wt/src/wt/server/gitstatusd_listener.py
- wt/src/wt/shared/config_file.py
- experimental/claude-history/claude_history_reader.py
- experimental/cotrl/llm_rl_experiment.py
- And 3 more...

---

## Medium Priority: String Comparisons and Assignments

### String Comparisons (81 total across 37 files)

**Example patterns found:**

```python
# ❌ BAD - String comparisons without enum safety
if status == "afk":
    ...
elif status == "active":
    ...

if auth_type == "key_path":
    return create_key_auth_context()
elif auth_type == "session":
    return create_session_context()
elif auth_type == "admin":
    return create_admin_context()

if runner_type == "claude_runner":
    runner = ClaudeRunner()
elif runner_type == "minicodex_runner":
    runner = MiniCodexRunner()
```

**High-occurrence comparisons:**
- `doc_type == "search"` (tana/)
- `type == "text"` (embedding output)
- `type == "function_call"` (OpenAI API)
- `auth_type == "key_path"` (gatelet/)
- `auth_type == "session"` (gatelet/)
- `auth_type == "admin"` (gatelet/)

### String Assignments (257 total across 109 files)

**Example patterns found:**

```python
# ❌ BAD - String assignments to categorical fields
return SleepUntilUserMessageResult(status="rejected", reason=violation)
return SleepUntilUserMessageResult(status="waiting_for_matrix")

ResponseFunctionCallOutput(type="function_call_output", call_id=tool_call.id, output=output)
ResponseInputText(type="input_text", text=content)

auth_type="none"  # In test setup
auth_type="bearer"  # Auth configuration
```

---

## Repeated String Literals Analysis

These strings appear frequently and indicate strong enum candidates:

| String | Count | Category | Recommended Enum |
|--------|-------|----------|-----------------|
| `"error"` | 50 | Error/Status | ErrorStatus, ErrorType |
| `"failed"` | 19 | Status | Status, OperationStatus |
| `"success"` | 14 | Status | Status, OperationStatus |
| `"completed"` | 12 | Status | Status, TaskStatus |
| `"status"` | 10 | Field names | Consider context-specific enums |
| `"admin"` | 8 | Auth Role/Type | AuthType, UserRole |
| `"pending"` | 7 | Status | Status, RequestStatus |
| `"warning"` | 6 | Log/Alert Level | LogLevel, AlertLevel |
| `"info"` | 4 | Log Level | LogLevel |
| `"debug"` | 3 | Log Level | LogLevel |

**Action:** For each high-frequency string, search for usage patterns and extract into appropriate enums.

---

## Detailed Violation Map by Module

### Critical Areas (multiple violations per module)

#### 1. **adgn/** - 15 violations
- **Status fields:** `agent/persist/__init__.py` (agent status)
- **Type fields:** `rspcache/events.py`, `rspcache/admin_app.py`
- **Auth type strings:** Used heavily in MCP bridges
- **Model names:** `agent/runtime/registry.py`, `git_commit_ai/cli.py`

#### 2. **gatelet/** - 5 violations
- **auth_type comparisons:** `server/auth/handlers.py`, `server/auth/webhook_auth.py`
- **Status fields:** `server/endpoints/webhook_view.py`
- **Log level:** `server/config.py`

#### 3. **llm/ducktape_llm_common/** - 4 violations
- **Model strings:** `config/models.py`, `config/clean_models.py`
- **Hook types:** `hooks/handler.py`

#### 4. **wt/** - 3 violations
- **Pull request state:** `shared/github_models.py` (but enum exists!)
- **General state:** `shared/fixtures.py`

#### 5. **ember/** - 2 violations
- **MIME type:** `object_store.py`
- **Message type:** `runtime/python_session.py`

### Files with Existing Enums (Good Patterns)

These files already use enums correctly:

- `wt/src/wt/shared/protocol.py` - Uses enums for DaemonHealthStatus, StartupPhase, StreamEventType
- `adgn/src/adgn/agent/persist/__init__.py` - Uses StrEnum for RunStatus, ApprovalOutcome, EventType
- `wt/src/wt/shared/configuration.py` - Uses StrEnum for CowMethod
- `adgn/src/adgn/agent/server/status_shared.py` - Uses StrEnum for various statuses

---

## Fix Strategy by Priority

### Priority 1: Critical String Fields (Start Here)

**Files to fix immediately:**

1. **adgn/src/adgn/agent/persist/__init__.py** - PolicyProposal.status
   ```python
   class ProposalStatus(StrEnum):
       PENDING = "pending"
       APPROVED = "approved"
       DENIED = "denied"

   class PolicyProposal(BaseModel):
       status: ProposalStatus  # Was: str
   ```

2. **wt/src/wt/shared/github_models.py** - GitHubPRResponse.state
   ```python
   class GitHubPRResponse(BaseModel):
       state: PRState  # Was: str (reuse existing enum!)
   ```

3. **adgn/src/adgn/agent/mcp_bridge/servers/agents.py** - ServerState.status
   ```python
   class ServerRunStatus(StrEnum):
       RUNNING = "running"
       STOPPED = "stopped"

   class ServerState(BaseModel):
       status: ServerRunStatus  # Was: str
   ```

### Priority 2: Literal to StrEnum (Consistency)

Files with 2+ Literal types should consolidate:

1. **adgn/src/adgn/agent/server/protocol.py**
   - Convert all `Literal[...]` to corresponding `StrEnum` classes
   - Reduces duplication and improves reusability

2. **adgn/src/adgn/openai_utils/types.py**
   - Check if OpenAI SDK provides types to use instead
   - Fall back to StrEnum if internal categorization needed

3. **llm/ducktape_llm_common/claude_linter_v2/config/models.py**
   - Convert Literal types to StrEnum for consistency

### Priority 3: String Comparisons (Refactor)

After fixing field types, update comparisons:

```python
# Before
if auth_context.auth_type == "key_path":
    ...
elif auth_context.auth_type == "session":
    ...

# After
from enum import StrEnum

class AuthType(StrEnum):
    KEY_PATH = "key_path"
    SESSION = "session"
    ADMIN = "admin"

if auth_context.auth_type == AuthType.KEY_PATH:
    ...
elif auth_context.auth_type == AuthType.SESSION:
    ...
```

Files with 5+ comparisons:
- `gatelet/gatelet/server/auth/` - auth_type comparisons
- `adgn/src/adgn/mcp/` - MCP-related type checks
- `tana/src/tana/export/` - doc_type comparisons

### Priority 4: API Response Types

For files parsing external API responses (OpenAI, Anthropic, etc.):

**Check if SDK provides types:**
```bash
# Example
python -c "from anthropic.types import Message; print(dir(Message))"
python -c "from openai.types import ChatCompletion; print(dir(ChatCompletion))"
```

If SDK types exist, use them directly instead of custom stringly-typed models.

---

## Implementation Notes

### Backward Compatibility

`StrEnum` fields remain fully compatible with string APIs:

```python
from enum import StrEnum
from pydantic import BaseModel

class Status(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"

class Request(BaseModel):
    status: Status

# Serializes to JSON as string
req = Request(status=Status.PENDING)
print(req.model_dump_json())  # {"status": "pending"}

# Deserializes from string
req2 = Request.model_validate({"status": "pending"})  # Works!
```

### Type Checking with Mypy

Add type-safe comparisons:

```python
# Enable strict comparisons via type checking
if status == Status.COMPLETE:  # ✓ Type-checked
    ...

# Typos caught at check time, not runtime
if status == Status.COMPLET:  # ✗ Mypy error
    ...
```

### IDE Support

With proper enums:
- ✓ Autocomplete shows valid values
- ✓ Rename refactoring works across codebase
- ✓ Jump-to-definition finds enum definition
- ✓ Type hints show valid options

---

## Specific File-by-File Recommendations

### High Priority Files

#### adgn/src/adgn/agent/persist/__init__.py
**Current:**
```python
class PolicyProposal(BaseModel):
    id: str
    status: str  # ← CRITICAL: use enum
    created_at: datetime
```

**Fix:**
```python
class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"

class PolicyProposal(BaseModel):
    id: str
    status: ProposalStatus
    created_at: datetime
```

#### wt/src/wt/shared/github_models.py
**Current:**
```python
class GitHubPRResponse(BaseModel):
    state: str  # ← CRITICAL: PRState enum exists!
    ...
```

**Fix:**
```python
class GitHubPRResponse(BaseModel):
    state: PRState  # ← Reuse existing enum
    ...
```

#### gatelet/gatelet/server/auth/handlers.py
**Current:**
```python
class AuthContext(Protocol):
    @property
    def auth_type(self) -> str:  # Returns "key_path", "session", "admin"
        ...

# Comparisons throughout:
if auth_type == "key_path":
    ...
```

**Fix:**
```python
class AuthType(StrEnum):
    KEY_PATH = "key_path"
    SESSION = "session"
    ADMIN = "admin"

class AuthContext(Protocol):
    @property
    def auth_type(self) -> AuthType:
        ...

# Type-safe comparisons:
if auth_type == AuthType.KEY_PATH:
    ...
```

---

## Summary of Recommended Actions

### Immediate (Critical)
- [ ] Fix 4 status fields to use StrEnum
- [ ] Fix 2 state fields (reuse existing enums where possible)
- [ ] Fix 10 type/kind fields with Literal or StrEnum
- [ ] Fix 2 log_level fields to use LogLevel enum

### Short-term (High Priority)
- [ ] Convert 36 Literal types to StrEnum across 29 files
- [ ] Create central enums module for shared types (AuthType, LogLevel, etc.)
- [ ] Update 81 string comparisons to use enum members

### Medium-term
- [ ] Update 257 string assignments to use enum values
- [ ] Review API response parsing for SDK type usage
- [ ] Add type-checking pre-commit hook to catch new violations

### Tools and References

**Python enum documentation:**
```
https://docs.python.org/3/library/enum.html#enum.StrEnum
```

**Pydantic enum support:**
```
https://docs.pydantic.dev/latest/concepts/types/#enums
```

**Suggested pattern for shared enums:**

Create `adgn/src/adgn/types/enums.py` or similar to centralize frequently-used enums:

```python
from enum import StrEnum

class AuthType(StrEnum):
    KEY_PATH = "key_path"
    SESSION = "session"
    ADMIN = "admin"

class Status(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"

class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

# Usage across modules:
# from adgn.types.enums import AuthType, Status, LogLevel
```

---

## Detection Method

This scan used:
1. **AST analysis** - Parsed Python files to find string-annotated fields
2. **Regex pattern matching** - Searched for string comparisons and assignments
3. **Ripgrep** - Scanned for repeated string literals
4. **Manual review** - Validated findings and assessed severity

**False positive rate:** Low (mostly literal pattern matches for review)
**Coverage:** 943 Python files across entire codebase

---

## Related Standards and Guidelines

- **Martin Fowler** on [Stringly-typed](https://martinfowler.com/bliki/StringlyTyped.html)
- **PEP 663** - Python Enum StrEnum support
- **Pydantic v2** - Built-in enum validation and serialization
- This codebase's own: **prompts/scans/stringly-typed.md**
