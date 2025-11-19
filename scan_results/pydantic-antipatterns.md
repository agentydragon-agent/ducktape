# Pydantic Antipatterns Code Quality Scan Report

**Date**: 2025-11-19
**Scan Definition**: `prompts/scans/pydantic-antipatterns.md`
**Total Python Files Scanned**: 943

---

## Executive Summary

This scan searched the codebase for violations of Pydantic best practices and patterns that degrade type safety, IDE support, and code maintainability. The main antipatterns sought were:

1. **Pattern 1**: Manual field-by-field `model_dump()` instead of using Pydantic's built-in serialization
2. **Pattern 2**: Manual field-by-field `model_validate()` instead of using Pydantic's validation
3. **Pattern 3**: Dict-style access on Pydantic model fields instead of attribute access
4. **Pattern 4**: Dicts/serialized forms in internal code (not at serialization boundaries)

---

## Findings by Pattern

### Pattern 1: Manual Field-by-Field `model_dump` (Serial­ization)

**Severity**: Low-Medium
**Count**: 2 findings

#### Finding 1.1: Conditional `model_dump()` at I/O Boundary
**File**: `/home/user/ducktape/experimental/ember_evals/executor.py:81-84`

```python
def write_json_artifact(self, path: Path, payload: Mapping[str, object] | BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

**Issue**: Conditional serialization pattern handling mixed BaseModel and untyped inputs.
**Location Context**: This is at an I/O boundary (writing to file), so the pattern is somewhat acceptable, but the function signature accepting `Mapping[str, object]` alongside `BaseModel` is problematic.
**Recommendation**: Consider requiring the input to always be a typed Pydantic model, or use a discriminated union with separate serialization logic.

#### Finding 1.2: Conditional `model_dump()` in Tool Conversion
**File**: `/home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py:201-209`

```python
def convert_responses_tools_to_chat_functions(tools_val: Any) -> list[dict[str, Any]] | None:
    tools = parse_tools_list(tools_val)
    if not tools:
        return None
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        payload = tool.model_dump(mode="json", exclude_none=True) if isinstance(tool, BaseModel) else dict(tool)
        normalized.append(payload)
    return normalized
```

**Issue**: Conditional serialization after parsing untyped input.
**Location Context**: At API boundary (converting tool formats), acceptable as output is serialized form.
**Recommendation**: If `parse_tools_list()` guarantees return type consistency, the isinstance check becomes unnecessary.

### Pattern 2: Manual Field-by-Field `model_validate` (Validation)

**Severity**: Low
**Count**: 0 findings

**Status**: No clear violations found. The codebase generally uses `Model.model_validate()` or `TypeAdapter(...).validate_python()` when converting from dicts to Pydantic models. Example of good pattern found in `/home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py:113-118`:

```python
async def read_dataset(dataset_path: Path) -> list[Sample]:
    items: list[Sample] = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if "anthropic_request" in rec:
                items.append(CCRSample.model_validate(rec))  # ✓ Direct validation
                continue
```

### Pattern 3: Dict-Style Access on Pydantic Model Fields

**Severity**: Low-Medium
**Count**: Multiple occurrences (mostly in boundary/test code, not internal logic)

#### Finding 3.1: Dict-style access on trajectory items
**File**: `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py:94-106`

```python
for item in trajectory:
    if isinstance(item, ToolCall) and item.tool_name in ("Write", "Edit", "MultiEdit"):
        args = item.arguments  # ← Correctly typed as dict[str, Any]
        if "file_path" in args:
            path = args["file_path"]
            if item.tool_name == "Write":
                content = args.get("content", "")
```

**Issue**: The `ToolCall.arguments` field is `dict[str, Any]` (by necessity for tool schemas), and the code uses dict-style access. This is ACCEPTABLE because:
- Tool arguments are inherently unstructured (come from LLM-generated tool calls)
- The field type correctly reflects this constraint
- No better alternative exists here

**Status**: ✓ Good practice (not an antipattern in this context)

#### Finding 3.2: Proper attribute access on Criterion models
**File**: `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py:236`

```python
criteria_desc = "\n".join([f"- {c.name}: {c.description}" for c in prepared_artifacts["criteria"]])
```

**Status**: ✓ Good pattern - uses attribute access (`c.name`, `c.description`) on typed `Criterion` models.

### Pattern 4: Dicts Outside Serialization Boundaries

**Severity**: Medium
**Count**: 148 occurrences of `dict[str, Any]` in adgn source (need manual review for each)

#### Finding 4.1: Functions accepting `dict[str, Any]` parameters
**Files with high density**: (20+ files identified)
- `/home/user/ducktape/adgn/src/adgn/agent/server/runtime.py`
- `/home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/servers/agents.py`
- `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py` (lines 31, 42, 54, 72, 108, etc.)
- `/home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py`
- `/home/user/ducktape/adgn/src/adgn/agent/persist/events.py`
- `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`
- `/home/user/ducktape/adgn/src/adgn/props/prompt_eval/server.py`

#### Finding 4.2: Example - GradingStrategy.collect_artifacts()
**File**: `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py:31-39`

```python
@abstractmethod
def collect_artifacts(self, context: GradingContext) -> dict[str, Any]:
    """Collect artifacts to be graded from the rollout and environment.

    Returns:
        Dictionary of artifacts to grade
    """
```

**Issue**: Method returns `dict[str, Any]`, which loses type safety downstream.
**Context**: This is at an internal abstraction boundary (between strategies and grader), not an I/O boundary.
**Downstream usage**: `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py:108, 138, 148, etc.`

```python
def prepare_for_grader(self, artifacts: dict[str, Any], config: OptimizerConfig) -> dict[str, Any]:
    """Prepare artifacts for the grading model."""
    files = artifacts.get("files", {})  # ← Untyped dict access
    t_mgr = TruncationManager(config)
```

**Recommendation**: Create typed Pydantic models for artifact collections:
```python
class ArtifactsCollection(BaseModel):
    files: list[FileInfo] | None = None
    final_message: str | None = None
    agent_output: str | None = None
    reference: str | None = None
    criteria: list[Criterion] = []

    @property
    def raw_dict(self) -> dict[str, Any]:
        """Convert to dict only at actual serialization boundaries."""
        return self.model_dump(mode="json", exclude_none=True)

# Then change signature:
@abstractmethod
def collect_artifacts(self, context: GradingContext) -> ArtifactsCollection:
    ...

def prepare_for_grader(self, artifacts: ArtifactsCollection, config: OptimizerConfig) -> ArtifactsCollection:
    ...
```

#### Finding 4.3: High-density `dict[str, Any]` modules
**Files requiring review** (sorted by occurrence count):
1. `/home/user/ducktape/adgn/src/adgn/agent/server/runtime.py` - 4+ occurrences
2. `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py` - 6 occurrences
3. `/home/user/ducktape/adgn/src/adgn/inop/engine/runner_factory.py` - 3 occurrences
4. `/home/user/ducktape/adgn/src/adgn/agent/persist/handler.py` - 3+ occurrences
5. `/home/user/ducktape/adgn/src/adgn/props/prompt_eval/server.py` - 3+ occurrences

---

## Patterns Present in Codebase

### ✓ Good Patterns Found

1. **Proper use of `@field_serializer`** in `/home/user/ducktape/adgn/src/adgn/rspcache/models.py:52-54`:
   ```python
   @field_serializer("status")
   def serialize_status(self, value: ResponseStatus) -> str:
       return value.value
   ```

2. **Correct use of `model_validate()`** in boundary code throughout `/home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py`

3. **Proper attribute access on typed models** in `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py:236`

4. **Discriminated unions** used correctly in `/home/user/ducktape/adgn/src/adgn/inop/engine/models.py:398-399`:
   ```python
   RunnerEnvironment = Annotated[DockerEnvironment | WorkspaceEnvironment, Field(discriminator="type")]
   ```

---

## Detection Statistics

| Pattern | Found | Severity | Action Required |
|---------|-------|----------|-----------------|
| Pattern 1: Manual `model_dump` | 2 | Low | Review, likely acceptable at boundaries |
| Pattern 2: Manual `model_validate` | 0 | - | None |
| Pattern 3: Dict-style access | Multiple | Low | Review context - may be necessary for tool args |
| Pattern 4: `dict[str, Any]` in internal code | 148 | Medium | Systematic review needed |

---

## Detailed File-by-File Review Candidates

### High Priority (Internal logic with dict[str, Any])

1. **`adgn/src/adgn/inop/grading/strategies.py`**
   - **Lines**: 31, 42, 54 (abstract methods returning `dict[str, Any]`)
   - **Lines**: 108, 138, 148, 167, 218, 232 (methods accepting/returning `dict[str, Any]`)
   - **Impact**: Core abstraction boundary - affects multiple implementations
   - **Recommendation**: Create typed artifact collection model

2. **`adgn/src/adgn/inop/engine/runner_factory.py`**
   - **Type**: Internal factory logic with untyped dicts
   - **Context**: Review whether config should be typed

3. **`adgn/src/adgn/agent/persist/events.py`**
   - **Type**: Event persistence layer with untyped dicts
   - **Context**: Review serialization boundaries

### Medium Priority (Boundary code, needs review)

1. **`adgn/src/adgn/llm/sysrw/run_eval.py:207`**
   - **Pattern**: Conditional `model_dump()` in tool conversion
   - **Status**: Acceptable if input consistency can be improved

2. **`experimental/ember_evals/executor.py:83`**
   - **Pattern**: Conditional `model_dump()` accepting mixed types
   - **Status**: Consider typed input requirement

---

## Recommendations

### 1. Create Typed Collection Models
For internal data structures currently typed as `dict[str, Any]`, create Pydantic BaseModel wrappers:
- `ArtifactsCollection` for grading artifacts
- `ConfigDict` models for configuration objects
- `EventPayload` for event data

**Benefits**:
- Full type safety throughout pipeline
- IDE autocomplete and refactoring support
- Runtime validation at boundaries
- Documentation via model docstrings

### 2. Eliminate Optional Dicts at Boundaries
Functions that check `isinstance(obj, BaseModel)` suggest inconsistent input types. Normalize to single typed input:

```python
# Before
def func(data: BaseModel | dict[str, Any]) -> None:
    payload = data.model_dump() if isinstance(data, BaseModel) else data

# After
def func(data: DataModel) -> None:
    payload = data.model_dump()
```

### 3. Review Tool Arguments Pattern
The pattern of storing `dict[str, Any]` for tool arguments is necessary (LLM-generated), but:
- Document this clearly in model docstrings
- Create helper methods for safe dict access with fallbacks
- Use TypedDict for known tool argument schemas

### 4. Audit Current `dict[str, Any]` Occurrences
Categorize the 148 occurrences into:
- **Boundary code** (JSON parsing, HTTP request/response) - acceptable
- **Tool schema code** (LLM-generated arguments) - necessary
- **Internal logic** (data transformation) - should be typed

Only the "internal logic" category requires fixes.

---

## Analysis Method

- **Automated search**: ripgrep patterns for `dict[str, Any]`, `model_dump()`, `model_validate()`, dict-style access
- **Manual review**: Selected files for context and usage patterns
- **Classification**: Evaluated each finding against anti­pattern criteria and serialization boundaries
- **Documentation**: Based on Pydantic v2 best practices per `prompts/scans/pydantic-antipatterns.md`

---

## Files Not Flagged (False Negatives)

The following patterns are acceptable and were NOT flagged as violations:

1. **Tool arguments as `dict[str, Any]`** - Necessary for LLM-generated parameters
2. **JSON parsing before validation** - Standard practice at I/O boundaries
3. **`model_dump()` at serialization boundaries** - Correct usage
4. **`TypeAdapter` usage in tests** - Appropriate for ad-hoc validation
5. **Conditional type checks** - When at actual boundaries (HTTP, files, DB)

---

## Next Steps

1. **Immediate**: Review high-priority files (grading strategies, persist events)
2. **Short-term**: Create typed collection models for artifact handling
3. **Medium-term**: Audit all 148 `dict[str, Any]` occurrences and categorize
4. **Long-term**: Enforce typing discipline in code review

---

## References

- Scan Definition: `/home/user/ducktape/prompts/scans/pydantic-antipatterns.md`
- Pydantic Serialization: https://docs.pydantic.dev/latest/concepts/serialization/
- Pydantic Validation: https://docs.pydantic.dev/latest/concepts/validators/
