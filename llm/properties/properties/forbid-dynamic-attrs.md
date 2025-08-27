---
title: Forbid dynamic attribute access and catching AttributeError
kind: outcome
---

Agent-edited code does not use `getattr`, `hasattr`, or `setattr`, and does not catch `AttributeError`. Attribute presence must be determined by types, not runtime probing.

## Scope
Applies only to agent‑added or agent‑edited hunks. Pre‑existing uses outside those edits do not count toward violations.

## Acceptance criteria (checklist)
- No usage of `getattr`, `hasattr`, or `setattr`
- No `except AttributeError` (including in multi-except or bare except that later filters to AttributeError), and no code paths that swallow missing attributes and continue silently
- Attribute access is type-safe by design (static types or explicit data structures)
- Code does not "guess" attributes by trying multiple names via `getattr`/`hasattr`
- Trivial guards do not swallow missing attributes; they fail fast instead of continuing silently

## Positive examples
```python
# Type-driven design: explicit attributes
class User:  # could be a dataclass/attrs/TypedDict as well
    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

u = User("Rai", "rai@example.com")
send(u.email)
```


## Negative examples
```python
# Dynamic probing — forbidden
if hasattr(obj, "email"):
    send(getattr(obj, "email"))
```

```python
# Dynamic assignment — forbidden
setattr(config, "timeout", 10)
```

```python
# Hiding type errors behind exception catching — forbidden
try:
    return obj.value
except AttributeError:
    return None
```

```python
# Obscuring types and swallowing errors — forbidden
# house: House (pydantic) with attributes: roof: Roof, door: Door, num_windows: int
if hasattr(house, "roof"):
    # Tries to guess attributes and continues even if structure is wrong
    print("house has", getattr(getattr(house, "roof", None), "material", None))
```

```python
# Guessing multiple attribute spellings — forbidden
if hasattr(item, "id") or hasattr(item, "identifier") or hasattr(item, "ID"):
    ident = getattr(item, "id", None) or getattr(item, "identifier", None) or getattr(item, "ID", None)
    use(ident)
```