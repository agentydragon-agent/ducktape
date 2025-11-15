# Scan: Verbosity Antipatterns

**Goal**: Prefer fewer lines over more lines when readability is same or better.

**Priority**: Medium

## Pattern: Unnecessary Type Ignores

Type ignore comments should exist **if and only if** they're necessary.

```python
# BAD: Unnecessary type ignore
header_token: str | None = request.headers.get("X-API-Key")  # type: ignore[assignment]
# (Headers.get() already returns str | None, no ignore needed)

# GOOD: Remove if not needed
header_token: str | None = request.headers.get("X-API-Key")

# GOOD: Keep if actually needed with explanation
result = some_badly_typed_lib()  # type: ignore[no-untyped-call]  # Third-party lib lacks stubs
```

**Detection**: Search for `# type: ignore` and verify each is necessary.

**Fix**: Remove and run mypy. If mypy passes, the ignore wasn't needed.

## Pattern: Single-Use Helper Functions

Functions called exactly once should usually be inlined.

```python
# BAD: Trivial wrapper called once
def _index_tree_oid(repo: pygit2.Repository) -> pygit2.Oid:
    return repo.index.write_tree()

# Later:
oid = _index_tree_oid(repo)

# GOOD: Inline it
oid = repo.index.write_tree()

# BAD: Intermediate variable for single use
resp = await self.model.responses_create(req)
result: str = first_assistant_text(resp)
return result

# GOOD: Return directly
return first_assistant_text(await self.model.responses_create(req))
```

**When helpers are OK**:
- Called multiple times
- Complex enough that name adds clarity
- Used for testing/mocking purposes
- Extracted to break up very long function

## Pattern: Missing Walrus Operator

Use `:=` to avoid repetition when checking and using a value.

```python
# BAD: Call function twice
def first_assistant_text(response: ResponsesResult) -> str:
    texts = all_assistant_text(response)
    if not texts:
        raise ValueError("No assistant message with text found")
    return texts[0]

# GOOD: Use walrus operator
def first_assistant_text(response: ResponsesResult) -> str:
    if not (texts := all_assistant_text(response)):
        raise ValueError("No assistant message with text found")
    return texts[0]

# BAD: Assign then check nullability
detail = await db.get_response_detail(identifier)
if detail is None:
    raise HTTPException(status_code=404, detail="Not found")
return process(detail)

# GOOD: Walrus with negation
if not (detail := await db.get_response_detail(identifier)):
    raise HTTPException(status_code=404, detail="Not found")
return process(detail)

# BAD: Assign then check
identifier = record.response_id or record.cache_key
if identifier:
    process(identifier)

# GOOD: Walrus in condition
if identifier := (record.response_id or record.cache_key):
    process(identifier)
```

## Pattern: Unnecessary Type Casts

Don't narrow types unnecessarily.

```python
# BAD: Widening type with cast
def list_mcp_entries(self) -> dict[str, ServerEntry]:
    meta = CompositorMetaClient(self._mcp_client)
    return cast(dict[str, Any], await meta.list_states())
    # meta.list_states() already returns dict[str, ServerEntry]!

# GOOD: Remove cast if types already match
def list_mcp_entries(self) -> dict[str, ServerEntry]:
    meta = CompositorMetaClient(self._mcp_client)
    return await meta.list_states()

# GOOD: Cast only when necessary with explanation
# Cast needed: getattr usage in list_states() makes mypy infer Any
return cast(dict[str, ServerEntry], await meta.list_states())
```

## Pattern: Unnecessary Intermediate Variables

Avoid variables that are immediately returned or used once.

```python
# BAD: Unnecessary intermediate
rr = await session.read_resource(parse_any_url(uri))
s = extract_single_text_content(rr)
return TypeAdapter(dict[str, Any]).validate_json(s)

# GOOD: Chain directly (if readable)
return TypeAdapter(dict[str, Any]).validate_json(
    extract_single_text_content(
        await session.read_resource(parse_any_url(uri))
    )
)

# ALTERNATIVE: Use meaningful intermediate if it improves clarity
resource = await session.read_resource(parse_any_url(uri))
json_text = extract_single_text_content(resource)
return TypeAdapter(dict[str, Any]).validate_json(json_text)
```

**When intermediate variables help**:
- Breaking up deeply nested calls (>3 levels)
- Name adds important semantic meaning
- Debugging (can inspect intermediate values)
- Used multiple times

## Pattern: Redundant Conditionals

Simplify if/elif chains where possible.

```python
# BAD: Redundant elif after if with narrowing type check
if isinstance(obj_any, pygit2.Tag):
    obj = obj_any.peel(pygit2.Commit)
elif isinstance(obj_any, pygit2.Commit):
    obj = obj_any
else:
    raise ValueError("...")

# BETTER: Check if peel() works on commits too
# If commit.peel(Commit) == commit, then:
obj = obj_any.peel(pygit2.Commit)  # Works for both Tag and Commit

# BAD: Fallback that should use primary key
identifier = record.response_id or record.cache_key

# GOOD: Use primary key directly (always present)
identifier = record.cache_key
```

## Pattern: Duplicated Error Information

Don't pass the same error info in multiple parameters.

```python
# BAD: error_reason duplicates error.message
error_reason = "Streaming proxy failure"
await db.record_error(
    key,
    error_reason=error_reason,  # Duplicates next line!
    response_id=response_id,
    error=ErrorPayload(message=error_reason),
)

# GOOD: Single source of truth
await db.record_error(
    key,
    response_id=response_id,
    error=ErrorPayload(
        type="streaming_failure",
        message="Streaming proxy encountered exception",
        detail={"exception": str(exc), "response_id": response_id},
    ),
)

# EVEN BETTER: Capture structured error info
except httpx.HTTPError as exc:
    await db.record_error(
        key,
        response_id=response_id,
        error=ErrorPayload(
            type="upstream_http_error",
            message=f"HTTP {exc.response.status_code}",
            detail={
                "status_code": exc.response.status_code,
                "url": str(exc.request.url),
                "response_body": exc.response.text[:500],
            },
        ),
    )
```

**Why structured details matter**:
- Generic "Streaming proxy failure" says nothing about what failed
- Capture exception type, status codes, URLs, stack traces
- Makes debugging and monitoring actually useful
- Enables querying/filtering by error type

## Pattern: Duplicated Exception Handlers

Don't copy-paste error handling - extract to helper or refactor flow.

```python
# BAD: Same error handling repeated multiple times
try:
    resp = await client.send(request_obj, stream=True)
except Exception as exc:  # noqa: BLE001
    await db.record_error(
        key,
        error_reason=str(exc),
        response_id=None,
        error=ErrorPayload(message=str(exc)),
    )
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}")

# ... later in same file ...
try:
    resp = await client.post(upstream_url, json=body)
except Exception as exc:  # noqa: BLE001
    await db.record_error(
        key,
        error_reason=str(exc),
        response_id=None,
        error=ErrorPayload(message=str(exc)),
    )
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}")

# GOOD: Extract error handling
async def _handle_upstream_error(key: str, exc: Exception) -> NoReturn:
    await db.record_error(
        key,
        response_id=None,
        error=ErrorPayload(
            type="upstream_exception",
            message=str(exc),
            detail={"exception_type": type(exc).__name__},
        ),
    )
    raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}") from exc

# Usage:
try:
    resp = await client.send(request_obj, stream=True)
except Exception as exc:  # noqa: BLE001
    await _handle_upstream_error(key, exc)

try:
    resp = await client.post(upstream_url, json=body)
except Exception as exc:  # noqa: BLE001
    await _handle_upstream_error(key, exc)
```

**Detection**: Search for similar `except Exception` blocks with same logic.

## General Principle

**Ask**: Does this line/variable/function make the code clearer or just longer?

- **Clearer**: Keep it
- **Just longer**: Remove it

**Examples of clear verbosity** (keep):
```python
# Descriptive intermediate for complex calculation
user_percentage = (active_users / total_users) * 100
formatted = f"{user_percentage:.1f}%"

# Breaking up deeply nested calls
user_data = fetch_user_data(user_id)
permissions = extract_permissions(user_data)
filtered = apply_filters(permissions, current_context)
```

**Examples of pointless verbosity** (remove):
```python
# Useless intermediate
x = foo()
return x  # Just: return foo()

# Trivial wrapper
def get_name(user):
    return user.name
# Just: user.name

# Unnecessary type annotation matching default
result: str | None = None  # Just: result = None
```

## Detection Strategy

1. Search for `# type: ignore` - verify each is needed
2. Search for single-call helper functions starting with `_`
3. Look for patterns like `x = foo(); return x`
4. Look for variables used exactly once
5. Check for `if x: y = x` patterns (walrus candidates)

## References

- [PEP 572 - Assignment Expressions (Walrus)](https://peps.python.org/pep-0572/)
- [Mypy Type Ignore](https://mypy.readthedocs.io/en/stable/common_issues.html#spurious-errors-and-locally-silencing-the-checker)
