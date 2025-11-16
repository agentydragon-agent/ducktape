# Pydantic Antipatterns Scan Results

**Scan Date:** 2025-11-16
**Codebase:** ducktape
**Scan Prompt:** `/home/user/ducktape/prompts/scans/pydantic-antipatterns.md`

## Summary

Scanned the ducktape codebase for two Pydantic antipatterns:
1. **Manual field-by-field model_dump**: Methods that manually call `model_dump()` on individual fields instead of using Pydantic's nested serialization
2. **Manual field-by-field model_validate**: Methods that manually construct objects field-by-field instead of using `model_validate()`

**Found:** 1 instance of Pattern 1 (manual field-by-field extraction after model_dump)
**Found:** 0 instances of Pattern 2 (manual field-by-field validation)

## Findings

### Pattern 1: Manual Field Extraction After model_dump

#### Instance 1: ResponsesDB._upsert_snapshot

**File:** `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`
**Lines:** 540-556

**Code:**
```python
async def _upsert_snapshot(self, session: AsyncSession, *, key: str, snapshot: FinalResponseSnapshot) -> None:
    existing = await session.get(ResponseSnapshot, key)
    payload = snapshot.model_dump(mode="json")
    if existing is None:
        new_row = ResponseSnapshot(
            key=key,
            status=payload["status"],
            response=payload["response"],
            error=payload["error"],
            token_usage=payload["token_usage"],
        )
        session.add(new_row)
    else:
        existing.status = payload["status"]
        existing.response = payload["response"]
        existing.error = payload["error"]
        existing.token_usage = payload["token_usage"]
```

**Why it matches the pattern:**
- Calls `snapshot.model_dump(mode="json")` to get a dict
- Manually extracts each field from the `payload` dict (`payload["status"]`, `payload["response"]`, etc.)
- This is unnecessary because the fields could be accessed directly from the `snapshot` Pydantic object

**Recommended fix:**
Access fields directly from the `snapshot` object instead of dumping and re-extracting:
```python
async def _upsert_snapshot(self, session: AsyncSession, *, key: str, snapshot: FinalResponseSnapshot) -> None:
    existing = await session.get(ResponseSnapshot, key)
    # For JSON serialization to DB, model_dump at the final boundary
    payload = snapshot.model_dump(mode="json")
    if existing is None:
        new_row = ResponseSnapshot(
            key=key,
            status=payload["status"],
            response=payload["response"],
            error=payload["error"],
            token_usage=payload["token_usage"],
        )
        session.add(new_row)
    else:
        # Directly assign from payload since we need JSON-serialized values
        existing.status = payload["status"]
        existing.response = payload["response"]
        existing.error = payload["error"]
        existing.token_usage = payload["token_usage"]
```

**Note:** Upon closer inspection, this code might be justified because:
1. The SQLAlchemy JSONB columns need JSON-serializable data (not Pydantic objects)
2. The `@field_serializer` on `FinalResponseSnapshot.status` converts the enum to `.value`
3. Nested Pydantic objects need to be serialized before storage in JSONB columns

However, the pattern could still be cleaner by using the serialized payload directly rather than constructing from individual field extractions. The current approach is verbose but functional.

## Pattern 2: Manual Field-by-Field Validation

**No instances found.**

The codebase properly uses:
- `model_validate()` for dict-to-model conversion (e.g., `ResponseSnapshot.to_model()` at line 139-142)
- Direct Pydantic model construction where appropriate
- Field validators (`@field_validator`) for custom parsing logic

### Notable Non-Antipatterns

The following patterns were examined but are NOT antipatterns:

1. **Type-conditional serialization** (`/home/user/ducktape/ember/src/ember/openai_agent.py:94`):
   ```python
   output = result.model_dump_json() if isinstance(result, BaseModel) else result
   ```
   This is appropriate for handling heterogeneous types where only some values are Pydantic models.

2. **List comprehension dumps** (`/home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py:464,468`):
   ```python
   json.dumps([msg.model_dump() for msg in prefix_messages], ensure_ascii=False)
   ```
   This is appropriate for serializing lists of Pydantic objects to JSON strings.

3. **Field serializers** (`/home/user/ducktape/adgn/src/adgn/rspcache/models.py:41-43`):
   ```python
   @field_serializer("status")
   def serialize_status(self, value: ResponseStatus) -> str:
       return value.value
   ```
   This is the RECOMMENDED pattern for custom field serialization (not an antipattern).

4. **Conditional tool serialization** (`/home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py:280`):
   ```python
   payload = tool.model_dump(mode="json", exclude_none=True) if isinstance(tool, BaseModel) else dict(tool)
   ```
   This is appropriate for handling mixed types in a tools list.

## Recommendations

1. **For the one instance found**: Review whether the `_upsert_snapshot` method truly needs to extract fields from the dumped dict, or if it could be refactored to be more direct. The current implementation works but is slightly verbose.

2. **Overall code quality**: The codebase generally follows Pydantic best practices:
   - Uses `@field_serializer` for custom serialization
   - Uses `model_validate()` for deserialization
   - Only uses `model_dump()` at I/O boundaries
   - Handles heterogeneous types appropriately

## Files Scanned

The scan covered all Python files in the ducktape repository, with particular focus on:
- `/home/user/ducktape/adgn/src/adgn/rspcache/*.py`
- `/home/user/ducktape/adgn/src/adgn/llm/**/*.py`
- `/home/user/ducktape/ember/src/ember/*.py`
- `/home/user/ducktape/claude/claude_hooks/**/*.py`
- All other Python files in the repository

## Conclusion

The ducktape codebase demonstrates good Pydantic practices overall. Only one instance of a potential antipattern was found, and even that instance may be justified by the requirements of storing Pydantic models in SQLAlchemy JSONB columns. No instances of manual field-by-field validation were found, indicating proper use of Pydantic's validation capabilities.
