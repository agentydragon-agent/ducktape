# Scan Results: Manual Serialization Patterns That Should Use Pydantic

**Scan Date**: 2025-11-19
**Scan ID**: manual-serde-needs-pydantic
**Total Violations Found**: 4 files with 6 distinct violation patterns

---

## Summary

This scan identified places in the codebase where manual JSON serialization/deserialization and dict construction patterns are used instead of leveraging Pydantic's built-in capabilities. These patterns are suspect because they lack type safety, automatic validation, and are error-prone.

**Key Finding**: Manual `json.loads()` with string-literal dict access and internal functions returning `list[dict]` with documented structures are the primary violations.

---

## Violation Details

### 1. CRITICAL: SQLite Persistence Layer - Multiple Manual JSON Patterns

**File**: `/home/user/ducktape/adgn/src/adgn/agent/persist/sqlite.py`

**Severity**: HIGH (affects core persistence)

#### Pattern A: Manual JSON Loading with MCPConfig

**Lines**: 204, 230, 246

**Code**:
```python
# Line 204
cfg = MCPConfig.model_validate(json.loads(r["specs"])) if r["specs"] else MCPConfig()

# Line 230
mcp_config=MCPConfig.model_validate(json.loads(r["specs"])) if r["specs"] else MCPConfig(),

# Line 246
mcp_config=MCPConfig.model_validate(json.loads(r["specs"])) if r["specs"] else MCPConfig(),
```

**Issues**:
- Manual `json.loads()` followed by `model_validate()` adds unnecessary step
- String-literal dict access `r["specs"]` appears 3+ times
- Pattern is repeated across multiple methods (DRY violation)
- No encapsulation for the fetch-parse-validate workflow

**Recommendation**:
Create a nested Pydantic model that handles JSON deserialization automatically:
```python
class AgentRowDB(BaseModel):
    id: str
    created_at: datetime
    specs: MCPConfig = Field(default_factory=MCPConfig)
    metadata: AgentMetadata

# Then use:
row = AgentRowDB.model_validate(db_row_dict)
# or better: create a database layer that returns typed rows
```

---

#### Pattern B: Manual JSON Loading for model_params

**Lines**: 507, 530

**Code**:
```python
# Line 507
model_params=json.loads(r["model_params"]) if r["model_params"] else None,

# Line 530
model_params=json.loads(r["model_params"]) if r["model_params"] else None,
```

**Issues**:
- Repeated pattern for optional JSON field
- Returns untyped dict instead of structured model
- No validation of model parameters structure

**Recommendation**:
```python
class ModelParams(BaseModel):
    """Typed model parameters."""
    # Add expected fields here
    model_config = ConfigDict(extra="allow")  # Allow unknown params if needed

class RunRowDB(BaseModel):
    id: str
    model_params: ModelParams | None = None
    # ... other fields
```

---

#### Pattern C: Manual Dict Construction from Database Row

**Lines**: 545-547

**Code**:
```python
row_dict = dict(r)
row_dict["payload"] = json.loads(r["payload"]) if r["payload"] else {}
out.append(parse_event(row_dict))
```

**Issues**:
- Creates intermediate dict with manual JSON parsing
- String-literal key access `r["payload"]`
- Passes untyped dict to downstream function

**Recommendation**:
```python
# Instead of manual dict construction:
row_dict = dict(r)
row_dict["payload"] = json.loads(r["payload"]) if r["payload"] else {}
out.append(parse_event(row_dict))

# Use a database model:
class EventRowDB(BaseModel):
    seq: int
    ts: datetime
    type: str
    payload: dict[str, Any]
    call_id: str | None = None
    tool_key: str | None = None

event = parse_event(EventRowDB.model_validate(dict(r)).model_dump())
```

---

### 2. CRITICAL: Container Output Collection - Untyped Dict Return

**File**: `/home/user/ducktape/adgn/src/adgn/inop/runners/containerized_claude.py`

**Severity**: MEDIUM (structure is simple but repeated)

**Lines**: 271-292

**Code**:
```python
async def collect_outputs(self) -> list[dict[str, str]]:
    self._ensure_container_ready()

    files: list[dict[str, str]] = []
    for file_path in self._output_dir.rglob("*"):
        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(self._output_dir).as_posix()
        if self._exclusion_spec.match_file(relative_path):
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            files.append({"path": relative_path, "content": content})  # <-- Antipattern
        except UnicodeDecodeError:
            continue

    return files
```

**Issues**:
- Returns `list[dict[str, str]]` with hardcoded structure (["path", "content"])
- This is **internal code** (not I/O boundary)
- Structure is **known at development time**
- Multiple accesses to literal keys ("path", "content")
- Docstring would need to document this structure

**Recommendation**:
```python
from pydantic import BaseModel

class OutputFile(BaseModel):
    """A collected output file from container execution."""
    path: str = Field(description="Relative path to file")
    content: str = Field(description="File contents")

async def collect_outputs(self) -> list[OutputFile]:
    files: list[OutputFile] = []
    for file_path in self._output_dir.rglob("*"):
        # ... existing logic ...
        files.append(OutputFile(path=relative_path, content=content))
    return files
```

**Impact**: Downstream code accessing `file["path"]` and `file["content"]` becomes `file.path` and `file.content` with IDE autocomplete and type safety.

---

### 3. CRITICAL: Event Parsing - Manual Dict Field Extraction

**File**: `/home/user/ducktape/adgn/src/adgn/agent/persist/events.py`

**Severity**: MEDIUM (manual field extraction with string literals)

**Lines**: 64-102 (function `parse_event`)

**Code**:
```python
def parse_event(d: dict[str, Any]) -> EventRecord:
    raw_type = d.get("type")           # <-- String literal access
    et = EventType(str(raw_type))
    seq = int(d.get("seq", 0))         # <-- String literal access
    ts_raw = d.get("ts")               # <-- String literal access
    ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))
    call_id = d.get("call_id")         # <-- String literal access
    tool_key = d.get("tool_key")       # <-- String literal access
    payload_raw = d.get("payload") or {}  # <-- String literal access

    payload: TypedPayload
    if et == EventType.USER_TEXT:
        payload = UserTextPayload(text=str(payload_raw.get("text", "")))  # <-- String literal access
    elif et == EventType.ASSISTANT_TEXT:
        payload = AssistantTextPayload(text=str(payload_raw.get("text", "")))  # <-- String literal access
    elif et == EventType.TOOL_CALL:
        payload = ToolCallPayload(
            name=str(payload_raw.get("name", "")),         # <-- String literal access
            args_json=payload_raw.get("args_json"),        # <-- String literal access
            call_id=str(payload_raw.get("call_id") or d.get("call_id") or ""),
        )
    # ... more manual field extraction ...

    return EventRecord(seq=seq, ts=ts, type=et, payload=payload, call_id=call_id, tool_key=tool_key)
```

**Issues**:
- Takes `dict[str, Any]` with **known structure at development time**
- **Multiple string-literal dict accesses** (type, seq, ts, call_id, tool_key, payload, text, name, args_json)
- **Manual validation/coercion** (int(), str(), isinstance checks, fromisoformat)
- Function is called from internal code in `sqlite.py` (database layer)
- Structure **should be** enforced at the boundary

**Recommendation**:
```python
# Option 1: Create a typed input model
class EventRowDict(BaseModel):
    """Typed representation of event row from database."""
    seq: int
    ts: str | datetime  # Auto-coerced by Pydantic
    type: str
    payload: dict[str, Any]
    call_id: str | None = None
    tool_key: str | None = None

    @field_validator('ts', mode='before')
    @classmethod
    def parse_ts(cls, v):
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v))

def parse_event(row: EventRowDict) -> EventRecord:
    # Access typed fields instead of dict keys
    et = EventType(row.type)
    # ... rest of logic, no more d.get() calls ...
```

**Current State**: The code **does** have Pydantic models for the payloads (good!) but **bypasses** them by parsing from untyped dicts instead of letting Pydantic handle the deserialization.

---

### 4. MEDIUM: Hook Input Models - Untyped Response Dict

**File**: `/home/user/ducktape/claude/claude_hooks/claude_hooks/inputs.py`

**Severity**: LOW-MEDIUM (less critical, response is external)

**Lines**: 83

**Code**:
```python
class PostToolInput(BaseHookInput):
    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    tool_name: str
    tool_input: Any
    tool_response: dict[str, Any] | list[dict[str, Any]] | str | None = None  # <-- Untyped
```

**Issues**:
- `tool_response` uses `dict[str, Any] | list[dict[str, Any]]` which is untyped
- While this is an I/O boundary (external tool responses vary), keeping it completely untyped defeats validation benefits
- No structure documentation except as a union of dict/list/str

**Recommendation** (if responses follow patterns):
```python
from pydantic import Field

class ToolResponse(BaseModel):
    """Base response structure if responses follow a pattern."""
    result: Any = None
    error: str | None = None
    # ... add expected fields ...

class PostToolInput(BaseHookInput):
    hook_event_name: Literal["PostToolUse"] = "PostToolUse"
    tool_name: str
    tool_input: Any
    # If responses follow a pattern, use: tool_response: ToolResponse | None = None
    # If truly dynamic, document the expected structure
    tool_response: dict[str, Any] | list[dict[str, Any]] | str | None = None
```

**Status**: Currently acceptable if responses are truly dynamic from external tools. Monitor if patterns emerge.

---

## Statistical Summary

| Category | Count | Files | Severity |
|----------|-------|-------|----------|
| **Manual JSON Deserialization** | 5 | 1 | HIGH |
| **Untyped Dict Return** | 1 | 1 | MEDIUM |
| **Manual Field Extraction** | 1 | 1 | MEDIUM |
| **Untyped Response Field** | 1 | 1 | LOW |
| **Total Violations** | 8 | 3 | - |

---

## Fix Priority

### Phase 1 (Critical)
1. **sqlite.py**: Refactor to use nested Pydantic models for database row deserialization
2. **containerized_claude.py**: Create `OutputFile` Pydantic model for `collect_outputs()`
3. **events.py**: Create `EventRowDict` model for structured event row parsing

### Phase 2 (Important)
4. **inputs.py**: Add documentation or refactor `tool_response` if patterns emerge

---

## Validation Strategy

After fixes, verify with:

```bash
# 1. Type checking passes
mypy --config-file pyproject.toml adgn/src/adgn/agent/persist/ adgn/src/adgn/inop/runners/

# 2. Tests still pass
pytest adgn/tests/agent/test_persist.py -v

# 3. Round-trip serialization works
python -c "
from adgn.agent.persist.models import EventRecord, OutputFile
record = EventRecord(...)
json_str = record.model_dump_json()
record2 = EventRecord.model_validate_json(json_str)
assert record == record2
"

# 4. No new linting issues
ruff check adgn/src/adgn/agent/persist/ --fix
```

---

## References

- Scan Definition: `prompts/scans/manual-serde-needs-pydantic.md`
- Pydantic Docs: https://docs.pydantic.dev/latest/
- Field Defaults: https://docs.pydantic.dev/latest/usage/fields/
- Validators: https://docs.pydantic.dev/latest/api/functional_validators/

---

## Notes

- **Not Violations**: Simple I/O boundary dicts (reading JSON from external APIs, passing data through unchanged) are acceptable and not flagged here.
- **Context Matters**: The distinction between "I/O boundary" and "internal code" is semantic and requires judgment. All flagged items are internal code or could be refactored to be strongly typed.
- **Incremental Adoption**: Pydantic models can be introduced incrementally. Start with the most frequently accessed/validated structures.

