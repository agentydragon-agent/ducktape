# Code Quality Scan: API Model Design Antipatterns

**Scan Date**: 2025-11-19
**Scan Source**: `prompts/scans/api-model-design.md`
**Scope**: Full ducktape codebase (primary focus: `adgn/src/adgn/rspcache/`)

---

## Executive Summary

This scan identifies violations of API model design best practices across the codebase. The primary focus is the `rspcache` module, which shows several instances of pattern violations related to untyped dictionaries, loose field types, and suboptimal API model structure.

**Violations Found**: 6 critical instances
**Affected Files**: 2 core files
**Patterns Identified**: Pattern 5 (Untyped Dicts) - dominant issue

---

## Pattern 5: Untyped Dicts Instead of Pydantic Models

### Issue: Database Layer (`responses_db.py`)

The `ResponseSnapshot` ORM model uses untyped `dict[str, Any]` for fields that should have proper types:

| File | Line | Field | Current Type | Issue | Recommended Type |
|------|------|-------|--------------|-------|-----------------|
| `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py` | 98 | `frame` | `Mapped[dict[str, Any]]` | No validation, loses structure of ResponseStreamEvent | `Mapped[ResponseStreamEvent]` with custom JSON serialization |
| `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py` | 120 | `request_body` | `Mapped[dict[str, Any]]` | Untyped OpenAI request payload | `Mapped[ResponsesRequest]` or proper OpenAI request type |
| `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py` | 147 | `response` | `Mapped[dict[str, Any] \| None]` | Should be `OpenAIResponse` | `Mapped[OpenAIResponse \| None]` with JSON adapter |
| `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py` | 148 | `error` | `Mapped[dict[str, Any] \| None]` | Should be `ErrorPayload` | `Mapped[ErrorPayload \| None]` with JSON adapter |
| `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py` | 149 | `token_usage` | `Mapped[dict[str, Any] \| None]` | Should be `ResponseUsage` | `Mapped[ResponseUsage \| None]` with JSON adapter |

### Code Snippet: responses_db.py (Lines 138-160)

```python
class ResponseSnapshot(Base):
    __tablename__ = "response_snapshots"

    cache_key: Mapped[str] = mapped_column(
        String, ForeignKey("responses.cache_key", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ResponseStatus] = mapped_column(
        SQLEnum(ResponseStatus, name="rspcache_snapshot_status", native_enum=False), nullable=False
    )
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # ❌ VIOLATION
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)      # ❌ VIOLATION
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True) # ❌ VIOLATION
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    response_rel: Mapped[Response] = relationship(back_populates="snapshot")

    def to_model(self) -> FinalResponseSnapshot:
        return FinalResponseSnapshot.model_validate(
            {"status": self.status, "response": self.response, "error": self.error, "token_usage": self.token_usage}
        )
```

**Issues with this design**:

1. **Type Loss**: The ORM layer stores untyped dicts. Only at conversion to `FinalResponseSnapshot` are types enforced.
2. **No Validation at DB Level**: Invalid payloads could be stored without detection.
3. **Runtime Errors**: Typos in nested field access won't be caught until runtime.
4. **Code Duplication**: The `to_model()` conversion duplicates field names between DB and Pydantic model.
5. **TODO Comment at Line 564**: Indicates uncertainty about the current design:
   ```python
   # TODO: Decide how to split what's stored in JSONB columns vs separate columns
   # Current: status as separate column, response/error/token_usage as JSONB
   # Consider: Could status also go in JSONB? Or extract more fields?
   ```

### Issue: Model Layer (`models.py`)

The `ErrorPayload` model has an overly permissive field:

| File | Line | Field | Current Type | Issue |
|------|------|-------|--------------|-------|
| `/home/user/ducktape/adgn/src/adgn/rspcache/models.py` | 37 | `detail` | `Any \| None` | Untyped error details allow any value without validation |

### Code Snippet: models.py (Lines 32-40)

```python
class ErrorPayload(BaseModel):
    """Lightweight proxy error payload captured by the rspcache proxy."""

    message: str | None = None
    code: str | None = None
    detail: Any | None = None  # ❌ VIOLATION - untyped error details

    model_config = ConfigDict(extra="allow")
```

**Issues**:

1. **Overly Permissive**: `Any` allows arbitrary values, including non-JSON types.
2. **No Documentation**: What should `detail` contain? This is undocumented.
3. **Inconsistent with OpenAI SDK**: OpenAI error structures have specific detail types.

---

## Pattern 1: Inconsistent Structure Between DB and API Models

### Finding: Mismatch Between DB `Response` and API `ResponseRecordModel`

**Status**: PARTIALLY RESOLVED
**Severity**: Low (API layer is well-typed, but mismatch creates complexity)

#### `Response` DB Model (`responses_db.py`, Lines 108-136)

```python
class Response(Base):
    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    response_id: Mapped[str | None] = mapped_column(String, unique=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("client_api_keys.id"))  # ✓ Properly FK'd
    model: Mapped[str] = mapped_column(String, nullable=False)
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # ❌ Untyped
    # ... other fields ...
    api_key: Mapped[ClientAPIKey | None] = relationship(back_populates="responses")  # ✓ Nested properly
```

#### `ResponseRecordModel` API Model (`admin_app.py`, Lines 68-92)

```python
class ResponseRecordModel(BaseModel):
    # ... same fields ...
    request_body: ResponsesRequest  # ✓ Properly typed!
    api_key: APIKeyModel | None = None  # ✓ Properly nested
    snapshot: FinalResponseSnapshot | None = None  # ✓ Well-structured
```

**Observation**: The API model (`ResponseRecordModel`) is actually well-designed:
- ✓ Properly typed `request_body` as `ResponsesRequest` (not `dict[str, Any]`)
- ✓ Nested `APIKeyModel` instead of flat fields
- ✓ Correctly uses nested `FinalResponseSnapshot` for snapshot data

**Recommendation**: Align DB layer typing with API layer. Consider:
1. Type `request_body` in DB model as well (if feasible with SQLAlchemy)
2. Or at minimum, document the conversion in `_to_response_model()` helper

---

## Pattern 4: Flattened API Models (RESOLVED)

**Status**: ✓ NOT VIOLATED
**Finding**: The codebase properly uses nested models in the API layer.

Example from `admin_app.py` (Lines 68-92):
```python
class ResponseRecordModel(BaseModel):
    # ... core fields ...
    api_key: APIKeyModel | None = None  # ✓ Properly nested, not flattened
    snapshot: FinalResponseSnapshot | None = None  # ✓ Properly nested structure
```

The design correctly keeps related data grouped in nested Pydantic models rather than flattening them. This is a good practice and should be maintained.

---

## Pattern 2: Duplicated Data Across Tables (RESOLVED)

**Status**: ✓ NOT VIOLATED
**Finding**: No significant data duplication detected.

Key fields are properly distributed:
- `Response.status` ← primary status
- `ResponseSnapshot.status` ← snapshot status (legitimate, captures state at snapshot time)
- `Response.request_body` ← request (once)
- `Response.response_id` ← response ID (once, indexed for lookup)

This is a properly normalized structure.

---

## Pattern 3: `_json` Suffix on DB Columns (NOT FOUND)

**Status**: ✓ NO VIOLATIONS
**Finding**: The codebase does not use `_json` suffixes on JSONB columns.

Example of good naming:
- ✓ `request_body: Mapped[dict[str, Any]]` (not `request_body_json`)
- ✓ `response: Mapped[dict[str, Any] | None]` (not `response_json`)
- ✓ `frame: Mapped[dict[str, Any]]` (not `frame_json`)

The type system already indicates JSON storage via `Mapped[dict[...]]` and JSONB column type.

---

## Summary Table: All Violations

| Pattern | Severity | Count | Files | Status |
|---------|----------|-------|-------|--------|
| **Pattern 5**: Untyped dicts | Critical | 6 | 2 | Needs immediate action |
| Pattern 1: Denormalized fields | Low | 0 | - | ✓ Resolved |
| Pattern 2: Duplicated data | Low | 0 | - | ✓ Resolved |
| Pattern 3: `_json` suffixes | Info | 0 | - | ✓ Resolved |
| Pattern 4: Flattened models | Low | 0 | - | ✓ Resolved |

---

## Detailed Recommendations

### High Priority: Fix Pattern 5 Violations in `responses_db.py`

#### Option A: Full Type Safety (Recommended)

Use SQLAlchemy's JSON type adapters with Pydantic models:

```python
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped

class ResponseSnapshot(Base):
    __tablename__ = "response_snapshots"

    # Option 1: Store as JSON with type hints via TypeDecorator
    response: Mapped[OpenAIResponse | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[ErrorPayload | None] = mapped_column(JSONB, nullable=True)
    token_usage: Mapped[ResponseUsage | None] = mapped_column(JSONB, nullable=True)

    # Keep frame as dict for now (it's raw ResponseStreamEvent)
    frame: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    def to_model(self) -> FinalResponseSnapshot:
        # Type conversion happens here
        return FinalResponseSnapshot(
            status=self.status,
            response=self.response if isinstance(self.response, dict) else self.response,
            error=self.error,
            token_usage=self.token_usage
        )
```

#### Option B: Keep DB Untyped, Improve Conversion (Pragmatic)

If full typing in the DB layer is impractical, improve the conversion layer:

```python
class ResponseSnapshot(Base):
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def to_model(self) -> FinalResponseSnapshot:
        """Convert DB row to typed Pydantic model with validation."""
        # Validate and type-cast at conversion boundary
        return FinalResponseSnapshot.model_validate({
            "status": self.status,
            "response": OpenAIResponse.model_validate(self.response) if self.response else None,
            "error": ErrorPayload.model_validate(self.error) if self.error else None,
            "token_usage": ResponseUsage.model_validate(self.token_usage) if self.token_usage else None,
        })
```

### Medium Priority: Fix `ErrorPayload.detail`

Replace untyped `Any` with a discriminated union or documented choice:

```python
from typing import Literal, Annotated

class ErrorPayload(BaseModel):
    """Lightweight proxy error payload captured by the rspcache proxy."""

    message: str | None = None
    code: str | None = None
    # Option 1: Discriminated union of known error detail types
    detail: OpenAIErrorDetail | dict[str, Any] | str | None = None

    # Option 2: Document that detail is OpenAI-specific
    # detail: dict[str, Any] | None = Field(
    #     None,
    #     description="OpenAI error detail object. See OpenAI API docs for structure."
    # )

    model_config = ConfigDict(extra="allow")
```

### Low Priority: Type `Response.request_body`

If feasible, align the DB layer with the API layer:

```python
class Response(Base):
    # Current:
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Consider:
    # request_body: Mapped[ResponsesRequest] = mapped_column(JSONB, nullable=False)
    # (requires TypeDecorator or custom type)
```

---

## Test Coverage Recommendations

When implementing fixes, ensure:

1. **Validation Tests**: Verify that invalid JSON payloads are rejected at the model boundary
   ```python
   def test_invalid_error_payload():
       with pytest.raises(ValidationError):
           ErrorPayload.model_validate({"detail": object()})  # Should fail for non-JSON
   ```

2. **Roundtrip Tests**: Ensure DB → ORM → API → JSON roundtrips preserve types
   ```python
   def test_response_snapshot_roundtrip():
       original = FinalResponseSnapshot(status=ResponseStatus.COMPLETE, ...)
       db_row = ResponseSnapshot.from_pydantic(original)
       recovered = db_row.to_model()
       assert recovered == original
   ```

3. **Integration Tests**: Verify the API layer correctly validates incoming data
   ```python
   def test_api_response_endpoint_validates():
       # POST invalid response should fail validation
       response = client.get("/api/responses/bad-id")
       assert response.status_code == 422 or 404
   ```

---

## References

- **Pydantic v2 JSON Serialization**: https://docs.pydantic.dev/latest/concepts/serialization/
- **SQLAlchemy Type Adapters**: https://docs.sqlalchemy.org/en/20/orm/declarative_columns.html
- **OpenAI SDK Types**: https://github.com/openai/openai-python/tree/main/src/openai/types
- **Best Practices**: `/home/user/ducktape/prompts/scans/api-model-design.md` (source of this scan)

---

## Scan Methodology

This scan was performed by:

1. **Reading the scan prompt** from `prompts/scans/api-model-design.md`
2. **Identifying violations** of each pattern through:
   - Grep searches for `Mapped[dict[str, Any]]` (Pattern 5)
   - Code review of rspcache module structure
   - Analysis of ORM ↔ Pydantic model alignment
3. **Cross-referencing** with project conventions from `adgn/AGENTS.md`
4. **Documenting** with file:line references and code snippets

**Automated Detection Aids Used**:
- Pattern matching for untyped dicts
- Manual code inspection for denormalization
- TODO/FIXME comment discovery

**Manual Analysis** was required for:
- Determining if untyped fields are intentional (they are not in this case)
- Understanding relationships between DB and API models
- Assessing conversion layer quality

---

**Report Generated**: 2025-11-19
**Scan Duration**: Automated + manual review
**Next Steps**: Prioritize Pattern 5 fixes per recommendations above
