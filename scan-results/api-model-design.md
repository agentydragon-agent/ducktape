# API Model Design Antipatterns - Scan Results

**Date**: 2025-11-16
**Codebase**: ducktape
**Scan Prompt**: `/home/user/ducktape/prompts/scans/api-model-design.md`

## Summary

Scanned the ducktape codebase for the 5 API model design antipatterns. Found **3 out of 5 patterns** with varying severity:

- **Pattern 1 (Denormalized Fields)**: 1 instance found in gatelet
- **Pattern 3 (_json Suffix)**: 0 instances found (good!)
- **Pattern 5 (Untyped Dicts)**: Multiple instances found in rspcache
- **Pattern 2 (Duplicated Data)**: Not definitively found
- **Pattern 4 (Flattened Structures)**: Not found (rspcache appears to have been refactored correctly)

## Findings by Pattern

### Pattern 1: Denormalized/Computed Fields in Models

#### Instance 1: WebhookPayload model (gatelet)

**File**: `/home/user/ducktape/gatelet/gatelet/server/models.py`
**Lines**: 31-47

**Issue**: The `WebhookPayload` model stores both the integration's foreign key AND a denormalized copy of the integration name:

```python
class WebhookPayload(Base):
    """Model for webhook payloads received by the service."""

    __tablename__ = "webhook_payloads"

    id = Column(Integer, primary_key=True)
    received_at = Column(DateTime, nullable=False, default=func.now())
    # Direct storage of integration name as it was when received
    integration_name = Column(
        String, nullable=False, comment="Source integration name when received (e.g., 'home-assistant')"
    )
    # Link to integration configuration
    integration_id = Column(Integer, ForeignKey("webhook_integrations.id"), nullable=True)
    payload = Column(JSON, nullable=False)

    # Relationship to integration configuration
    integration_config = relationship("WebhookIntegration", back_populates="payloads")
```

**Why it matches Pattern 1**:
- Stores both `integration_id` (foreign key to `webhook_integrations.id`) AND `integration_name` (denormalized string copy)
- The comment explicitly acknowledges this is "direct storage of integration name as it was when received"
- Creates data duplication - the integration name is already available via `integration_config.name`
- No type safety - flat string doesn't tell you what integration it references
- Inconsistent - has a relationship (`integration_config`) but also stores denormalized data

**Recommended fix**: Either rely solely on the relationship, or if historical name preservation is truly needed, document why this denormalization is intentional (e.g., audit trail for renamed integrations).

---

### Pattern 3: `_json` Suffix on DB Columns

**Status**: ✅ **No instances found**

The codebase does not use `_json` suffixes on database columns. All JSON columns use clean names like `frame`, `request_body`, `response`, `error`, `token_usage`, `payload`, and `auth_config`.

**Note**: There is one code reference to `frame.frame_json` in `/home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py:172`, but the actual database column is named `frame` (not `frame_json`). This appears to be either a typo or stale code that should access `frame.frame` instead.

---

### Pattern 5: Untyped Dicts Instead of Pydantic Models

Multiple instances found in the rspcache module where `dict[str, Any]` is used when proper types exist.

#### Instance 1: Response.request_body (DB model)

**File**: `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`
**Line**: 108

```python
class Response(Base):
    # ...
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
```

**Why it matches Pattern 5**:
- Stores OpenAI API request bodies as untyped `dict[str, Any]`
- OpenAI SDK provides proper request types (e.g., for chat completions)
- No validation - accepts malformed data
- No autocomplete or type safety

---

#### Instance 2: ResponseSnapshot.response, error, token_usage (DB model)

**File**: `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`
**Lines**: 129-131

```python
class ResponseSnapshot(Base):
    __tablename__ = "response_snapshots"

    # ...
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

**Why it matches Pattern 5**:
- All three fields have proper types available:
  - `response` → `OpenAIResponse` (from `openai.types.responses`)
  - `error` → `ErrorPayload` (defined in `models.py`)
  - `token_usage` → `ResponseUsage` (from `openai.types.responses`)
- The Pydantic model (`FinalResponseSnapshot`) already uses the proper types
- DB layer loses type information that gets reconstructed later

**Note**: The `to_model()` method on line 139-142 converts from untyped dicts to properly typed `FinalResponseSnapshot`, but this means validation only happens at read time, not write time.

---

#### Instance 3: ResponseFrame.frame (DB model)

**File**: `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`
**Line**: 91

```python
class ResponseFrame(Base):
    # ...
    frame: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
```

**Why it matches Pattern 5**:
- Stores `ResponseStreamEvent` objects as untyped dicts
- The proper type (`ResponseStreamEvent`) is available from `openai.types.responses`
- Code uses `FRAME_ADAPTER: TypeAdapter[ResponseStreamEvent]` to parse it later

---

#### Instance 4: ResponseRecordModel.request_body (API model)

**File**: `/home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py`
**Line**: 88

```python
class ResponseRecordModel(BaseModel):
    # ...
    # TODO: Type this properly (OpenAI request model)
    request_body: dict[str, Any]
```

**Why it matches Pattern 5**:
- API model exposes untyped dict
- Explicit TODO comment acknowledges this should be properly typed
- Should use OpenAI request types

---

### Pattern 2: Duplicated Data Across Tables

**Status**: ⚠️ **Potentially present, needs verification**

The scan prompt mentions "Response.token_usage vs ResponseSnapshot.token_usage" as an example from rspcache. However, examining the current code:

- `Response` table (line 96-119 in `responses_db.py`) does NOT have a `token_usage` field
- `ResponseSnapshot` table (line 122-142) DOES have `token_usage`

This suggests the duplication may have already been removed, or the pattern description refers to an older version. The current code appears correct in this regard - `Response` stores basic metadata while `ResponseSnapshot` stores the detailed final state.

---

### Pattern 4: Flattened API Models vs Nested DB Relationships

**Status**: ✅ **Not found - appears to have been refactored**

The scan prompt mentions this as an issue in "adgn/rspcache/admin_app.py (before refactor)". The current code shows proper nesting:

**File**: `/home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py`
**Lines**: 67-93

```python
class ResponseRecordModel(BaseModel):
    """API model for cached OpenAI API responses."""
    # ...

    # Nested relationships (typed)
    api_key: APIKeyModel | None = None
    snapshot: FinalResponseSnapshot | None = None
```

This is the GOOD pattern - the API model properly nests related models instead of flattening them. The `FinalResponseSnapshot` is also properly typed with nested models (despite the underlying DB storage using untyped dicts - see Pattern 5).

---

## Additional Finding: Potential Code Error

**File**: `/home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py`
**Line**: 172

```python
def _to_frame_model(frame: ResponseFrame) -> FrameRecordModel:
    payload = FRAME_ADAPTER.validate_python(frame.frame_json)  # ← frame_json doesn't exist
```

The code accesses `frame.frame_json`, but the `ResponseFrame` model defines the field as just `frame` (line 91 of `responses_db.py`). This appears to be either:
1. A bug - should be `frame.frame`
2. Stale code from when the column was named `frame_json`
3. There's a property/alias not visible in the model definition

---

## Recommendations

### High Priority

1. **Fix the frame_json access** in admin_app.py line 172 - verify if this is a bug or if there's a missing property
2. **Type request_body fields** - Complete the TODO on line 88 of admin_app.py by using proper OpenAI request types
3. **Document WebhookPayload denormalization** - If storing `integration_name` separately is intentional for audit/historical reasons, document this clearly; otherwise, rely on the relationship

### Medium Priority

4. **Type DB JSON columns** - Consider using SQLAlchemy's type decorators or custom types to enforce validation at the DB layer:
   - `ResponseSnapshot.response` → use a custom type backed by `OpenAIResponse`
   - `ResponseSnapshot.error` → use a custom type backed by `ErrorPayload`
   - `ResponseSnapshot.token_usage` → use a custom type backed by `ResponseUsage`
   - `ResponseFrame.frame` → use a custom type backed by `ResponseStreamEvent`
   - `Response.request_body` → use proper OpenAI request types

### Low Priority

5. **Review other dict[str, Any] usage** - Found 20+ instances across the codebase; many are legitimately untyped (e.g., arbitrary JSON from external APIs), but review each for typing opportunities

---

## Files Reviewed

- `/home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py`
- `/home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py`
- `/home/user/ducktape/adgn/src/adgn/rspcache/models.py`
- `/home/user/ducktape/gatelet/gatelet/server/models.py`
- `/home/user/ducktape/gatelet/gatelet/server/endpoints/webhook_receive.py`
- Plus grep searches across the entire codebase

---

## Conclusion

The ducktape codebase shows good practices in some areas (proper model nesting, avoiding `_json` suffixes) but has room for improvement in typing JSON columns and avoiding denormalization. The rspcache module in particular would benefit from using the proper OpenAI SDK types throughout the stack instead of untyped dictionaries.
