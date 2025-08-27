---
title: No one-off variables or trivial pass-through wrappers
kind: outcome
---

Agent-edited code does not introduce single-use "one-off" variables that merely forward into the next call without adding non‑obvious value, and does not add pass‑through functions whose only behavior is to immediately call another function and return its result without a visible reason (e.g., boundary, adaptation, validation).

## Scope
Applies only to agent‑added or agent‑edited hunks. Pre‑existing patterns outside those edits do not count toward violations.

## Acceptance criteria (checklist)
- Single-use variables that simply forward into the next call are inlined, unless they convey non‑obvious meaning, are reused, or materially improve readability
- Functions that only call another function and return its result are absent, unless they add visible value (e.g., input normalization/validation, signature adaptation, dependency boundary, retries/backoff, structured logging/metrics, deprecation shim) and the reason is evident
- Test helpers/wrappers are acceptable when they encapsulate setup defaults or fixtures; public API adapters are acceptable when they adapt names/types/contracts (documented inline)

## Positive examples (acceptable)
```python
# Inline instead of one-off variable
await client.post_json({
    "type": "update_sensor_states",
    "data": [u.model_dump(exclude_none=True) for u in updates],
})
```

```python
# Test helper encapsulates setup defaults (acceptable)
def make_user(name: str = "Rai", email: str = "rai@example.com") -> User:
    return User(name=name, email=email)
```

## Negative examples (violations)
```python
# One-off variable used only to feed next call (attribute name)
state_key = self.config.state_management.state_key
tool_state = getattr(session, state_key, None)
# should be inlined
# tool_state = getattr(session, self.config.state_management.state_key, None)
```

```python
# One-off iterator used only to feed collection
result_iterator = tool_instance.process(message)
content_sections = await collect_content_sections(result_iterator)
# should be inlined
# content_sections = await collect_content_sections(tool_instance.process(message))
```

```python
# One-off error object immediately returned
error = ErrorResponse(error="Session not found", session_id=session_id)
return error.to_text_content()
# should be inlined
# return ErrorResponse(error="Session not found", session_id=session_id).to_text_content()
```

```python
# Trivial pass-through wrapper with identical signature and call
def foo(a, b, c, d):
    return bar(a, b, c, d)
```