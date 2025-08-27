---
title: Use walrus for trivial immediate conditions
kind: outcome
---


When a simple condition depends on a value computed immediately before, the value is bound inline with the walrus operator (:=) inside the condition.

## Scope
Applies only to agent‑added or agent‑edited hunks. Pre‑existing code outside those edits does not count toward violations.

## Acceptance criteria (checklist)
- Patterns like `if x`, `if not x`, `if x is None`, `if x is not None`, or `if x == <literal>` that depend on a freshly computed value use `:=` to bind inline
- The bound expression is the immediately evaluated value (e.g., a function call or awaitable)
- Do not create a separate one‑off variable assignment solely to feed the next `if` when `:=` would be equivalent and readable

## Positive examples
```python
# Async: bind inline for a trivial guard
if not (session := await session_manager.get_session(session_id)):
    return ErrorResponse(error="Session not found").to_text_content()

response = PageStackResponse(
    session_id=session_id,
    current_cursor=session.current_cursor,
    page_count=len(session.page_stack),
    pages=[create_page_info(p, session.current_cursor) for p in session.page_stack],
)
return response.to_text_content()
```

```python
# Synchronous
if (item := cache.get(key)) is not None:
    return item
```

```python
# Equality to simple literal
if (code := compute_status()) == 1:
    handle_ok()
```

## Negative examples
```python
# One-off assignment only to feed the next if — should use walrus
session = await session_manager.get_session(session_id)
if not session:
    return ErrorResponse(error="Session not found").to_text_content()
```

```python
# Redundant two-step when a single `if (x := ...) is not None:` suffices
result = maybe_get()
if result is not None:
    use(result)
```

## While reader loops

### Positive examples
```python
# File-like object
while chunk := f.read(8192):
    process(chunk)

# Async stream
while (line := await stream.readline()):
    handle(line)
```

### Negative examples
```python
# Two-step read loop instead of walrus
chunk = f.read(8192)
while chunk:
    process(chunk)
    chunk = f.read(8192)

# Async version
line = await stream.readline()
while line:
    handle(line)
    line = await stream.readline()
```