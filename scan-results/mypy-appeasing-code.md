# Scan Results: Mypy-Appeasing Code Antipatterns

## Summary

Scanned the ducktape codebase for mypy-appeasing code antipatterns as defined in `/home/user/ducktape/prompts/scans/mypy-appeasing-code.md`. Found **19 instances** of unnecessary casts and **0 instances** of other antipatterns (unnecessary TypeAdapter intermediate variables, redundant isinstance assertions, or assign-to-typed-variable patterns).

The TypeAdapter instances found are all module-level constants that are reused multiple times, which is the correct pattern for performance and readability.

## Findings

### 1. Unnecessary Casts

#### 1.1. `/home/user/ducktape/adgn/src/adgn/rspcache/codegen.py`

**Line 24:**
```python
return cast(dict[str, Any], schema)
```
- **Context:** `get_openapi()` returns `dict[str, Any]` according to FastAPI docs
- **Why it matches:** The return type of `get_openapi()` is already `dict[str, Any]`, making the cast redundant

**Line 34:**
```python
return cast(dict[str, Any], data)
```
- **Context:** `yaml.safe_load()` returns `Any`, but the code already checks `if not isinstance(data, dict)` before this line
- **Why it matches:** After the isinstance check, mypy should know that `data` is a dict. The cast appears to be for more specific typing (`dict[str, Any]` vs just `dict`)

---

#### 1.2. `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`

**Line 435:**
```python
return cast(Response | None, result.scalar_one_or_none())
```
- **Context:** SQLAlchemy query result
- **Why it matches:** This is likely a case where SQLAlchemy typing could be improved. Modern SQLAlchemy 2.0+ with proper type annotations on the select() statement should return the correct type without casting.

**Line 461:**
```python
return cast(list[ResponseFrame], frames)
```
- **Context:** `frames = list(result.scalars())`
- **Why it matches:** With proper SQLAlchemy 2.0 typing using `select(ResponseFrame)`, the `scalars()` method should return an iterator of `ResponseFrame`, making this cast unnecessary.

---

#### 1.3. `/home/user/ducktape/adgn/src/adgn/rspcache/__init__.py`

**Line 116:**
```python
return cast(str, token)
```
- **Context:** After checking `if token:` on a `str | None` variable
- **Why it matches:** The truthiness check narrows the type from `str | None` to `str`, so the cast is redundant. Mypy should understand this pattern.

---

#### 1.4. `/home/user/ducktape/adgn/src/adgn/inop/prompting/truncation_utils.py`

**Lines 49, 63, 66:**
```python
[fi.model_dump() for fi in cast(list[FileInfo], files)]  # Line 49
for fi in cast(list[FileInfo], files):  # Line 63
for d in cast(list[dict[str, str]], files):  # Line 66
```
- **Context:** Handling `list[dict[str, str]] | list[FileInfo]` union after runtime type check
- **Why it matches:** After checking `isinstance(files[0], FileInfo)`, the type should be narrowed. This is a pattern that could be refactored to avoid casts by normalizing the type earlier or using type guards.

---

#### 1.5. `/home/user/ducktape/adgn/src/adgn/inop/io/file_ops.py`

**Line 31:**
```python
return cast(list[FileInfo], truncated_models)
```
- **Context:** `truncated_models = t_mgr.truncate_files_by_tokens(files_info, ...)`
- **Why it matches:** This suggests the return type of `truncate_files_by_tokens()` is poorly typed (likely returns `list[dict[str, str]] | list[FileInfo]` or `Any`). The function signature should be fixed or overloaded to return the correct type.

---

#### 1.6. `/home/user/ducktape/adgn/src/adgn/inop/io/logging_utils.py`

**Line 130:**
```python
return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
```
- **Context:** `structlog.get_logger()` return type
- **Why it matches:** This could be resolved by:
  1. Installing `types-structlog` type stubs if they exist
  2. Checking if newer structlog versions have better typing
  3. Using a properly typed wrapper function

---

#### 1.7. `/home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py`

**Lines 153, 156:**
```python
tu = cast(list[FileInfo], truncated_union)  # Line 153
td = cast(list[dict[str, str]], truncated_union)  # Line 156
```
- **Context:** Same pattern as truncation_utils.py - handling union after runtime check
- **Why it matches:** Could be eliminated with type guards or by improving the typing of `truncate_files_by_tokens()`

---

#### 1.8. `/home/user/ducktape/adgn/src/adgn/openai_utils/retry.py`

**Line 49:**
```python
call = cast(Callable[P, Awaitable[T]], wrapped)
```
- **Context:** After wrapping a function with tenacity retry decorator
- **Why it matches:** The tenacity decorator should preserve the callable signature. This might be an old workaround for poor tenacity typing. Should check if newer tenacity versions have better generic support.

---

#### 1.9. `/home/user/ducktape/adgn/src/adgn/openai_utils/model.py`

**Lines 315, 344:**
```python
return cast(ResponsesResult, result)  # Lines 315, 344
```
- **Context:** Inside wrapper/adapter classes
- **Why it matches:** If the `responses_create()` method is properly typed to return `ResponsesResult`, these casts are redundant. The protocol/interface should be tightened.

---

#### 1.10. `/home/user/ducktape/adgn/src/adgn/openai_utils/types.py`

**Lines 55, 59:**
```python
payload["effort"] = cast(ReasoningEffortLiteral, effort_value)  # Line 55
return cast(ReasoningParams, payload)  # Line 59
```
- **Context:** Building a typed dict from validated string values
- **Why it matches:** If `effort_value` is already validated as `ReasoningEffortLiteral` type, the cast is unnecessary. The return cast could be eliminated by using a TypedDict constructor or proper type narrowing.

---

#### 1.11. `/home/user/ducktape/adgn/src/adgn/openai_utils/probe/ui.py`

**Line 123:**
```python
return cast(Family | None, self.family_choices[self.family_idx])
```
- **Context:** Accessing a list that should already be typed
- **Why it matches:** If `self.family_choices` is properly typed as `list[Family | None]`, the cast is unnecessary.

---

#### 1.12. `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/utils/__init__.py`

**Lines 139, 171:**
```python
return cast(F, wrapper)  # Lines 139, 171
```
- **Context:** Decorator pattern returning wrapped function
- **Why it matches:** This is a common pattern in decorators where TypeVar `F` is used. The cast might be necessary due to limitations in mypy's decorator typing, but it's worth checking if `@functools.wraps` with proper ParamSpec could eliminate it.

---

### 2. TypeAdapter Usage

All TypeAdapter instances found are **module-level constants** that are reused multiple times. This is the **correct pattern** per the scan prompt, as it avoids creating the adapter repeatedly. Examples:

- `/home/user/ducktape/adgn/src/adgn/rspcache/models.py`: `FRAME_ADAPTER`, `RESPONSE_ADAPTER`, `ERROR_ADAPTER`, `USAGE_ADAPTER` (used in multiple places)
- `/home/user/ducktape/adgn/src/adgn/rspcache/events.py`: `_EVENT_ADAPTER` (used in `parse_event()`)
- `/home/user/ducktape/ember/src/ember/config.py`: `_SLEEP_POLICY_ADAPTER` (used in validation)
- `/home/user/ducktape/ember/src/ember/openai_agent.py`: `_INPUT_ITEM_ADAPTER` (used multiple times)

**No antipatterns found** - all are reusable module-level constants.

---

### 3. Inline TypeAdapter Calls

Several files use inline `TypeAdapter(...).validate_python()` calls without storing the adapter:

- `/home/user/ducktape/adgn/src/adgn/inop/io/task_loader.py:127`: Single use validation
- `/home/user/ducktape/adgn/src/adgn/llm/sysrw/openai_typing.py`: Multiple inline uses in helper functions (lines 171, 197, 287, 297, 304)

These are **acceptable** as they're one-off validations in helper functions that are themselves called multiple times. The antipattern would be storing the adapter in a local variable and then using it once.

---

### 4. Other Antipatterns

**No instances found** of:
- Redundant isinstance assertions (all `assert isinstance` found are in tests for validation)
- Assign-to-typed-variable followed by immediate return

---

## Recommendations

1. **SQLAlchemy casts** (responses_db.py): Upgrade to SQLAlchemy 2.0+ style with `Mapped[]` annotations and `select()` with proper generics
2. **Union narrowing casts** (truncation_utils.py, strategies.py): Implement TypeGuard functions or refactor to eliminate the union type
3. **Library typing improvements**:
   - Check for `types-structlog` package
   - Review tenacity typing in recent versions
   - Check FastAPI's `get_openapi()` return type annotations
4. **Decorator casts**: Review if modern Python typing with ParamSpec can eliminate decorator wrapper casts
5. **Simple narrowing** (__init__.py:116): Remove cast after truthiness check - mypy should handle this

## Validation Steps

Before removing any cast:
1. Check the library's actual return type in source/stubs
2. Run `mypy` to confirm the cast is unnecessary
3. Check if there are type stubs packages available
4. Consider library version upgrades for better typing
