# Scan Results: Manual Serialization Patterns That Should Use Pydantic

**Date**: 2025-11-16
**Scan Definition**: `/home/user/ducktape/prompts/scans/manual-serde-needs-pydantic.md`

## Executive Summary

This scan identified **2 remaining** locations where internal code uses manual dict manipulation and `.isoformat()` calls that should be replaced with Pydantic models. Three findings have been applied.

**Applied**: Findings #1 (Ultra Long CoT), #2 (RL Experiment), #4 (Grader Actions) - commit `add445b`

## Key Findings

### ~~1. LLM Message History - Ultra Long CoT~~ ✅ APPLIED

**Status**: Fixed in commit `add445b`
- Replaced `list[dict[str, str]]` with `list[Message]`
- Added Pydantic models for Message and LogEntry
- Automatic datetime serialization

### ~~2. RL Experiment Conversation History~~ ✅ APPLIED

**Status**: Fixed in commit `add445b`
- Replaced `list[dict[str, str]]` with `list[Message]`
- Added EpisodeData, StepData, SummaryData models
- Automatic datetime handling throughout

### ~~4. Grader Action Sequences~~ ✅ APPLIED

**Status**: Fixed in commit `add445b`
- Replaced `list[dict[str, Any]]` with `list[Action]`
- Property access instead of `.get()` calls
- Type-safe action handling

---

## Remaining Findings

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

1. ~~**High Priority** (Internal logic, frequently accessed)~~ ✅ **COMPLETED**
   - ~~LLM message history (ultra_long_cot_o4.py, llm_rl_experiment.py)~~ ✅ Applied
   - ~~Grader action sequences~~ ✅ Applied

2. **Medium Priority** (Configuration/persistence) - **REMAINING**:
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

**Progress**: 3 of 5 high-priority findings have been applied (commit `add445b`).

**Remaining**: 2 medium-priority findings in Claude linter session management code. These are less critical as they're in configuration/persistence code rather than hot-path logic.

**Impact**: The applied changes significantly improved type safety in:
- LLM message handling (ultra-long CoT, RL experiments)
- Grader action sequences

All high-priority findings (frequently accessed internal logic) are now complete. Remaining findings are lower priority configuration/persistence code.
