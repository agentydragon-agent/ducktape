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
await http.post_json({
    "type": "render_track",
    "data": [t.model_dump(exclude_none=True) for t in tracks],
})
```

```python
# Test helper encapsulates setup defaults (acceptable)
def make_user(name: str = "Rai", email: str = "rai@example.com") -> User:
    return User(name=name, email=email)
```

```python
# Inline attribute name usage (positive counterpart)
value = getattr(record, settings.schema.primary_field, None)
```

```python
# Inline iterator usage (positive counterpart)
frames = await collect_frames(video.iter_frames())
```

```python
# Direct return of constructed value (positive counterpart)
return FailureResponse(error="Not found", resource_id=rid).to_text_content()
```

```python
# One-line chain (positive counterpart)
return build_engine_spec(snapshot_path).as_runner().ready()
```

## Negative examples (violations)
```python
# One-off variable used only to feed next call (attribute name)
field_name = settings.schema.primary_field
value = getattr(record, field_name, None)
```

```python
# One-off iterator used only to feed collection
frames_iter = video.iter_frames()
frames = await collect_frames(frames_iter)
```

```python
# One-off error object immediately returned
error = FailureResponse(error="Not found", resource_id=rid)
return error.to_text_content()
```

```python
# Trivial pass-through wrapper with identical signature and call
def foo(a, b, c, d):
    return bar(a, b, c, d)
```

```python
# Trivial chain via one-off variables; should be one line

def probe_cache(namespace=None) -> bool:
    cfg = build_cache_config(namespace)
    client = cfg.make_client()
    return client.ready()
# should be inlined
# return build_cache_config(namespace).make_client().ready()
```