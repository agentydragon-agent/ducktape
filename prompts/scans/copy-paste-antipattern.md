# Scan: Copy-Paste Antipattern

**Goal**: Don't copy-paste code - extract, abstract, or refactor instead.

**Priority**: High

## General Principle

**If you're about to copy-paste code, STOP.**

Copy-paste creates:
- Multiple sources of truth (bugs waiting to happen)
- Maintenance burden (fix in N places)
- Harder refactoring
- Code bloat

## What Counts as Copy-Paste?

Not just literal code - **patterns** too:

### Literal Code Copy-Paste

```python
# BAD: Copied error handling
try:
    resp = await client.send(request)
except Exception as exc:
    await db.record_error(key, error=ErrorPayload(message=str(exc)))
    raise HTTPException(status_code=502, detail=f"Failed: {exc}")

# ... 50 lines later ...
try:
    resp = await client.post(url, json=body)
except Exception as exc:
    await db.record_error(key, error=ErrorPayload(message=str(exc)))
    raise HTTPException(status_code=502, detail=f"Failed: {exc}")

# GOOD: Extract once
async def _handle_upstream_error(key: str, exc: Exception) -> NoReturn:
    await db.record_error(key, error=ErrorPayload(message=str(exc)))
    raise HTTPException(status_code=502, detail=f"Failed: {exc}") from exc
```

### Pattern Copy-Paste

Even if variables differ, same *pattern* = copy-paste:

```python
# BAD: Pattern copied (different variables, same structure)
if user.is_admin:
    admin_name = user.name
    admin_email = user.email
    admin_role = "admin"
    save_admin(admin_name, admin_email, admin_role)

if user.is_moderator:
    mod_name = user.name
    mod_email = user.email
    mod_role = "moderator"
    save_moderator(mod_name, mod_email, mod_role)

if user.is_viewer:
    viewer_name = user.name
    viewer_email = user.email
    viewer_role = "viewer"
    save_viewer(viewer_name, viewer_email, viewer_role)

# GOOD: Extract pattern
def save_user_with_role(user: User, role: str, saver: Callable):
    saver(user.name, user.email, role)

if user.is_admin:
    save_user_with_role(user, "admin", save_admin)
if user.is_moderator:
    save_user_with_role(user, "moderator", save_moderator)
if user.is_viewer:
    save_user_with_role(user, "viewer", save_viewer)

# EVEN BETTER: Use dispatch table
ROLE_SAVERS = {
    "admin": save_admin,
    "moderator": save_moderator,
    "viewer": save_viewer,
}

role = user.get_role()
if saver := ROLE_SAVERS.get(role):
    saver(user.name, user.email, role)
```

## Common Copy-Paste Patterns

### 1. Field-by-Field Assignment

```python
# BAD: Copied field assignment pattern
new_row = ResponseSnapshot(
    key=key,
    status=payload["status"],
    response=payload["response"],
    error=payload["error"],
    token_usage=payload["token_usage"],
)

# Later:
existing.status = payload["status"]
existing.response = payload["response"]
existing.error = payload["error"]
existing.token_usage = payload["token_usage"]

# GOOD: Loop or unpacking
new_row = ResponseSnapshot(cache_key=key, **payload)
for field, value in payload.items():
    setattr(existing, field, value)
```

### 2. Validation Logic

```python
# BAD: Copied validation pattern
if not user.name:
    raise ValueError("Name required")
if len(user.name) > 100:
    raise ValueError("Name too long")

if not user.email:
    raise ValueError("Email required")
if len(user.email) > 100:
    raise ValueError("Email too long")

# GOOD: Extract validator
def validate_required_field(value: str, name: str, max_len: int = 100):
    if not value:
        raise ValueError(f"{name} required")
    if len(value) > max_len:
        raise ValueError(f"{name} too long (max {max_len})")

validate_required_field(user.name, "Name")
validate_required_field(user.email, "Email")
```

### 3. Conversion Logic

```python
# BAD: Copied conversion pattern
def _to_response_model(record: Response) -> ResponseRecordModel:
    return ResponseRecordModel(
        cache_key=record.cache_key,
        response_id=record.response_id,
        model=record.model,
        # ... 10 more fields
    )

def _to_frame_model(frame: ResponseFrame) -> FrameRecordModel:
    return FrameRecordModel(
        ordinal=frame.ordinal,
        frame_type=frame.frame_type,
        event_id=frame.event_id,
        # ... 8 more fields
    )

# GOOD: Use from_attributes
class ResponseRecordModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    # Fields automatically mapped from Response

# Usage: ResponseRecordModel.model_validate(record)
```

### 4. Error Construction and Exception Handlers

```python
# BAD: Copied exception handlers with error construction
try:
    resp = await client.send(request_obj, stream=True)
except Exception as exc:
    await db.record_error(
        key,
        error_reason=str(exc),
        response_id=None,
        error=ErrorPayload(message=str(exc)),
    )
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}")

# ... 100 lines later ...
try:
    resp = await client.post(upstream_url, json=body)
except Exception as exc:
    await db.record_error(
        key,
        error_reason=str(exc),
        response_id=None,
        error=ErrorPayload(message=str(exc)),
    )
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}")

# GOOD: Extract error handler with structured details
async def _record_upstream_error(
    db: ResponsesDB,
    key: str,
    *,
    exc: Exception,
    response_id: str | None = None,
) -> None:
    """Record an upstream request failure with structured error details."""
    await db.record_error(
        key,
        error_reason=f"Upstream request failed: {type(exc).__name__}",
        response_id=response_id,
        error=ErrorPayload(
            message="Upstream request failed",
            detail={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        ),
    )

# Usage - much cleaner and consistent
try:
    resp = await client.send(request_obj, stream=True)
except Exception as exc:
    await _record_upstream_error(db, key, exc=exc)
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}")

try:
    resp = await client.post(upstream_url, json=body)
except Exception as exc:
    await _record_upstream_error(db, key, exc=exc)
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}")
```

**Benefits of extraction:**
- Single source of truth for error recording logic
- Consistent structured error details (error_type, error_message)
- Easier to add telemetry, logging, or monitoring
- Can evolve error handling in one place

## Detection Strategy

1. **Manual code review**: Look for similar-looking blocks
2. **Pattern search**: Search for repeated function calls with similar args
3. **Ask yourself**: "Have I written this before?"
4. **3-strikes rule**: If same pattern appears 3+ times, extract it

## When Copy-Paste is OK

Rare cases where duplication is acceptable:

- **Tests**: Test cases often have similar structure (but consider parametrized tests)
- **Different domains**: Coincidentally similar code for unrelated concepts
- **Temporary duplication**: During refactoring, before extraction
- **Performance**: Hot path where abstraction costs too much (profile first!)

## Fix Priority

1. **Error handling**: Extract immediately - errors are critical
2. **Validation**: Extract to prevent inconsistency
3. **Conversions**: Use Pydantic `from_attributes` or factory functions
4. **Business logic**: Extract to prevent divergence

## References

- [Don't Repeat Yourself (DRY)](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself)
- [Rule of Three (refactoring)](https://en.wikipedia.org/wiki/Rule_of_three_(computer_programming))
