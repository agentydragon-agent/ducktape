# Scan Results: Manual Serialization Patterns That Should Use Pydantic

**Date**: 2025-11-16
**Scan Definition**: `/home/user/ducktape/prompts/scans/manual-serde-needs-pydantic.md`

## Executive Summary

This scan identified **6 high-priority** locations where internal code uses manual dict manipulation, `list[dict]` with known structure, and `.isoformat()` calls that should be replaced with Pydantic models. These patterns reduce type safety, prevent IDE autocomplete, and require manual validation instead of leveraging Pydantic's built-in capabilities.

## Key Findings

### 1. LLM Message History - Ultra Long CoT (HIGH PRIORITY)

**File**: `/home/user/ducktape/llm/ultra-long-cot/ultra_long_cot_o4.py`

**Issues**:
- Lines 74, 84: Functions accept `list[dict[str, str]]` for message history
- Line 145: Manual dict construction: `messages = [{"role": "system", "content": system_prompt}]`
- Line 167, 204-206, 248: Repeated `{"role": ..., "content": ...}` construction
- Line 296: Manual dict with `.isoformat()`: `{"timestamp": datetime.now().isoformat(), ...}`

**Evidence**:
```python
def count_messages_tokens(messages: list[dict[str, str]]) -> int:
    """Count total tokens in message history"""
    total = 0
    for msg in messages:
        # Each message has role tokens + content tokens + formatting
        total += count_tokens(msg["role"]) + count_tokens(msg["content"]) + 5
    return total
```

**Why It's Bad**:
- String-literal dict access (`msg["role"]`, `msg["content"]`) in internal code
- No validation - can pass `{"foo": "bar"}` and get KeyError at runtime
- Structure documented in comments instead of enforced by types
- Manual timestamp formatting instead of automatic serialization

**Recommended Fix**:
```python
from pydantic import BaseModel, Field
from datetime import datetime

class Message(BaseModel):
    role: str
    content: str

class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    turn: int
    user_input: str
    response_segments: int
    total_output_tokens: int
    context_used_percentage: float
    messages: list[Message]
    usage_details: list[dict]  # Could be further typed

# Usage:
messages: list[Message] = [Message(role="system", content=system_prompt)]
# Serialize: log_entry.model_dump_json()
```

---

### 2. RL Experiment Conversation History (HIGH PRIORITY)

**File**: `/home/user/ducktape/experimental/cotrl/llm_rl_experiment.py`

**Issues**:
- Lines 187, 247: `self.conversation_history: list[dict[str, str]] = []`
- Lines 120, 140: Manual dict with `.isoformat()` for episode logging
- Lines 159-160: Manual dict construction with timestamps

**Evidence**:
```python
class LLMRLAgent:
    def __init__(self, model: str):
        self.conversation_history: list[dict[str, str]] = []

    async def get_action(...):
        self.conversation_history.append({"role": "user", "content": prompt})
        # Later:
        self.conversation_history.append({"role": "assistant", "content": action_str})
```

**Why It's Bad**:
- Same as #1 - internal state using untyped dicts
- Episode logging manually constructs dicts with `.isoformat()`
- No compile-time verification of message structure

**Recommended Fix**:
```python
class Message(BaseModel):
    role: str
    content: str

class EpisodeData(BaseModel):
    timestamp: datetime
    model: str
    environment: str
    run_num: int
    episode_num: int
    total_reward: float
    num_steps: int
    states: list[Any]
    actions: list[int]
    rewards: list[float]

class LLMRLAgent:
    def __init__(self, model: str):
        self.conversation_history: list[Message] = []
```

---

### 3. File Truncation Utils (HIGH PRIORITY - Partial Fix Available)

**File**: `/home/user/ducktape/adgn/src/adgn/inop/prompting/truncation_utils.py`

**Issues**:
- Lines 47, 59, 66, 88, 115-116, 128: Mixed use of `list[dict[str, str]]` and `list[FileInfo]`
- Lines 104-105: String-literal dict access: `file_info["path"]`, `file_info["content"]`
- The codebase already has a `FileInfo` Pydantic model but doesn't consistently use it

**Evidence**:
```python
def truncate_file_content_by_size(
    self, files: list[dict[str, str]], max_size: int, purpose: str | None = None
) -> dict[str, str]:
    """..."""
    for file_info in files:
        path = file_info["path"]      # String-literal access
        content = file_info["content"]  # String-literal access
```

**Why It's Bad**:
- The code already imports and uses `FileInfo` model in some places
- But then falls back to `list[dict[str, str]]` in other methods
- Creates inconsistency and prevents full type safety

**Recommended Fix**:
- Remove `list[dict[str, str]]` variants entirely
- Always use `list[FileInfo]` (the Pydantic model already exists)
- Update `truncate_file_content_by_size` to accept `list[FileInfo]`

**Note**: This is a **partial migration** - the code already has the right model, just needs to use it consistently.

---

### 4. Grader Action Sequences (HIGH PRIORITY)

**File**: `/home/user/ducktape/claude/claude_optimizer/graders/generic_graders.py`

**Issues**:
- Line 40: `action_sequence: list[dict[str, Any]]` in `AgentRollout` dataclass
- Lines 150, 328: `json.loads(output_item.arguments)` without validation
- Lines 282-283: Manual dict access in loop: `action.get("tool")`, `action.get("type")`

**Evidence**:
```python
@dataclass
class AgentRollout:
    action_sequence: list[dict[str, Any]]  # Tool calls and actions Claude made

async def grade_agent_rollout(self, rollout: AgentRollout) -> GradeResult:
    for i, action in enumerate(rollout.action_sequence, 1):
        action_type = action.get("tool", action.get("type", "unknown"))
        action_summary += f"{i}. {action_type}: {action.get('description', str(action)[:100])}\n"
```

**Why It's Bad**:
- Action sequences are internal data with known structure
- Using `.get()` with fallbacks suggests uncertain schema
- Manual `json.loads()` without Pydantic validation

**Recommended Fix**:
```python
class Action(BaseModel):
    tool: str | None = None
    type: str | None = None
    description: str = ""
    # Add other known fields

@dataclass
class AgentRollout:
    action_sequence: list[Action]

# For JSON parsing:
analysis_data = AnalysisResult.model_validate(json.loads(output_item.arguments))
```

---

### 5. Claude Linter Session Rules (MEDIUM PRIORITY)

**File**: `/home/user/ducktape/llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/session/state.py`

**Issues**:
- Line 28: `rules: list[dict[str, Any]] = field(default_factory=list)`
- No validation of rule structure

**Evidence**:
```python
@dataclass
class SessionState:
    rules: list[dict[str, Any]] = field(default_factory=list)

    def add_rule(self, rule: dict[str, Any]) -> None:
        """Add a session-specific rule."""
        self.rules.append(rule)
```

**Why It's Bad**:
- Rules have known structure (predicate, action, created, expires)
- No validation when adding rules
- Type annotation `dict[str, Any]` is too permissive

**Recommended Fix**:
```python
class Rule(BaseModel):
    predicate: str
    action: str  # Could be Literal["allow", "deny"]
    created: datetime
    expires: datetime | None = None

@dataclass
class SessionState:
    rules: list[Rule] = field(default_factory=list)

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)
```

---

### 6. Session Manager Persistence (MEDIUM PRIORITY)

**File**: `/home/user/ducktape/llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/session/manager.py`

**Issues**:
- Lines 44, 65: Manual dict construction with `.isoformat()`
- Line 111: Manual dict for rules with `.isoformat()`
- Inconsistent use of `dict[str, Any]` for session data

**Evidence**:
```python
def _load_session(self, session_id: SessionID) -> dict[str, Any]:
    # ...
    return {"id": session_id, "created": datetime.now().isoformat(), "rules": []}

def track_session(self, session_id: SessionID, working_dir: Path) -> None:
    session_data = self._load_session(session_id)
    session_data.update({
        "last_seen": datetime.now().isoformat(),
        "directory": str(working_dir.resolve())
    })
```

**Why It's Bad**:
- Manual `.isoformat()` instead of Pydantic automatic serialization
- Session data structure not validated
- Mix of string timestamps and datetime objects

**Recommended Fix**:
```python
class SessionData(BaseModel):
    id: str
    created: datetime
    last_seen: datetime | None = None
    directory: Path | None = None
    rules: list[Rule] = Field(default_factory=list)
    notification_id: int | None = None

def _load_session(self, session_id: SessionID) -> SessionData:
    session_file = self._session_file(session_id)
    if session_file.exists():
        return SessionData.model_validate_json(session_file.read_text())
    return SessionData(id=session_id, created=datetime.now())

def _save_session(self, session_id: SessionID, session_data: SessionData) -> None:
    session_file = self._session_file(session_id)
    session_file.write_text(session_data.model_dump_json(indent=2))
```

---

## Lower Priority Findings

### Trilium API Response Parsing

**Files**: Multiple files in `/home/user/ducktape/trilium/`
- `search_hack.py`: Lines 23, 29, 33-34, 74, 84-85, etc.
- `papers/trilium_paper_uploader.py`: Lines 63-64, 75-76, etc.

**Status**: **ACCEPTABLE** - These are I/O boundary responses from external API
- Reading JSON from Trilium API (external system)
- Not internal code - this is the correct place for dict manipulation
- Would need to create Pydantic models for Trilium API schema to improve

---

## Scan Methodology

### Patterns Searched

1. **String-literal dict access**: `rg '\["[a-zA-Z_]+"\]' --type py`
2. **list[dict] parameters**: `rg 'list\[dict\[str' --type py`
3. **Manual isoformat**: `rg '\.isoformat\(\)' --type py`
4. **json.loads usage**: `rg 'json\.loads' --type py`
5. **Dataclasses**: `rg '@dataclass' --type py`

### Filtering Criteria

**Excluded** (by design):
- Test files (`tests/`, `test_*.py`)
- I/O boundary code (reading external APIs, parsing config files)
- Passthrough/forwarding code (just relaying data unchanged)

**Included** (scan targets):
- Internal functions passing structured data between components
- Data with known, documented structure
- Repeated dict construction patterns
- Manual validation/serialization code

---

## Impact Analysis

### Type Safety
- **Before**: Runtime KeyErrors, no autocomplete, no validation
- **After**: Compile-time type checking, IDE support, automatic validation

### Maintenance
- **Before**: Structure documented in comments/docstrings
- **After**: Structure enforced by code, self-documenting

### Serialization
- **Before**: Manual `json.dumps()`, `.isoformat()`, dict construction
- **After**: `model.model_dump_json()` handles all serialization

---

## Recommended Prioritization

1. **High Priority** (Internal logic, frequently accessed):
   - LLM message history (ultra_long_cot_o4.py, llm_rl_experiment.py)
   - File truncation utils (partial migration needed)
   - Grader action sequences

2. **Medium Priority** (Configuration/persistence):
   - Claude linter session management
   - Session rules

3. **Low Priority** (External API responses):
   - Trilium API parsing (could improve but not critical)

---

## Migration Strategy

For each finding:

1. **Define Pydantic Models**
   - Create models for known structures
   - Add validation rules, constraints
   - Use `Field()` for descriptions

2. **Update Function Signatures**
   - Replace `list[dict[str, str]]` with `list[ModelName]`
   - Update type hints

3. **Replace Manual Code**
   - Dict access → property access
   - `json.loads()` → `Model.model_validate_json()`
   - Manual dict construction → `Model(...)`
   - `.isoformat()` → automatic datetime handling

4. **Update Tests**
   - Construct typed models in tests
   - Verify serialization round-trips

---

## Examples of Good Pydantic Usage in Codebase

The codebase already uses Pydantic well in several places:

1. **adgn/src/adgn/inop/engine/models.py**: `FileInfo` model (should be used more consistently)
2. **llm/mcp/habitify/habitify_mcp_server/types.py**: Excellent discriminated unions, validators
3. Various Pydantic models throughout the `adgn` package

These serve as good templates for new models.

---

## Conclusion

The ducktape codebase has **6 high-priority locations** where Pydantic models would significantly improve type safety, reduce manual validation code, and prevent runtime errors. The most impactful changes are in LLM message handling and file truncation utilities.

Most findings are in active development areas (LLM tooling, experimental code), making this a good time to standardize on Pydantic before the patterns spread further.
