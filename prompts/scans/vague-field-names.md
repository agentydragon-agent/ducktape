# Scan: Vague Field Names

## Context
@../shared-context.md

## Overview

Field names should be **explicit and self-documenting within their usage context**. This is a **semantic analysis**, not pattern matching.

A field name is vague when:
- **Context doesn't clarify its purpose** (e.g., `cfg` in a function with multiple config objects)
- **Multiple similar entities exist** (e.g., `id` when there are user IDs, request IDs, etc. nearby)
- **The containing scope is generic** (e.g., `key` in a class called `Response`)

A field name is NOT vague when:
- **Container name provides full context** (e.g., `User.id` is obviously the user's ID)
- **Only one of its kind exists** in the scope (e.g., single `status` field in focused class)
- **Convention makes it obvious** (e.g., SQLAlchemy model's `id` primary key)

## Pattern: Context-Based Ambiguity

### BAD: Generic container + vague field

```python
# BAD: "Response" is too generic - response to what? Which ID?
class Response(BaseModel):
    key: str  # Hash? Database key? API key? Cache key?
    id: str   # ID of what? Request? Response? User?
    name: str # Name of what?

# BAD: Multiple configs in scope - which one?
def process_rollout(rollout, task, cfg, grading_cfg, model_cfg):
    cfg.get_value()  # Which config? Optimizer? Task? Model?
```

### GOOD: Specific container OR single entity in scope

```python
# GOOD: Container name makes it obvious
class User(BaseModel):
    id: int        # Obviously user_id due to class name
    name: str      # Obviously user name due to class name

class CacheEntry(BaseModel):
    key: str       # Obviously cache key due to class name

# GOOD: Only one config in scope
def validate_config(cfg: OptimizerConfig) -> bool:
    return cfg.validate()  # Only one cfg, name is fine

# BAD → GOOD: Multiple configs? Use specific names
def process_rollout(
    rollout,
    task,
    optimizer_cfg,      # ✓ Specific
    grading_cfg,        # ✓ Specific
    model_cfg           # ✓ Specific
):
    optimizer_cfg.get_value()  # ✓ Clear which config
```

## Common Vague Names (context-dependent)

These are only problematic when context doesn't clarify:

| Name | Vague When | Clear When |
|------|-----------|-----------|
| `id` | Generic class like `Response`, `Data` | Specific model like `User.id`, `Product.id` |
| `name` | Generic class, multiple name types nearby | Specific model like `Category.name` |
| `key` | Generic class, unclear which type of key | `CacheEntry.key`, `EncryptionContext.key` |
| `data` | Passed around, unclear what it contains | Single data field in focused class |
| `cfg`, `config` | Multiple configs in same scope | Only config in scope |
| `value` | Generic getter/setter | `ThresholdConfig.value`, `Setting.value` |
| `type` | Without discriminated union context | `type: Literal["user", "admin"]` in union |

## Detection Strategy

**Not**: "Find all fields named 'id'"
**Yes**: "Find fields where name doesn't clarify purpose in context"

1. **Look for generic container names** with generic field names:
   - `Response.id`, `Data.key`, `Result.name` → likely vague
   - `User.id`, `CacheEntry.key`, `Product.name` → likely fine

2. **Check for multiple similar entities in scope**:
   ```python
   # BAD: Three IDs in scope, which is which?
   def link_items(id: str, parent_id: str, user_id: str):
       process(id)  # Which ID?
   ```

3. **Look for abbreviated names in complex contexts**:
   - `cfg` alone in function with 5 different config types → vague
   - `cfg` as only config parameter → fine

## Fix Strategy

1. **Add prefix/suffix clarifying purpose**:
   ```python
   key → cache_key, api_key, encryption_key
   id → user_id, request_id, session_id
   ```

2. **Add docstring if renaming breaks compatibility**:
   ```python
   class Response(BaseModel):
       """Response record.

       Attributes:
           key: SHA256 hash of request body (used for cache lookups)
       """
       key: str  # Still vague, but at least documented
   ```

3. **Best: Rename and update all usages**:
   ```python
   # Find all usages
   rg "\.key\b"

   # Rename in model
   key → cache_key

   # Update all call sites
   response.key → response.cache_key
   ```

## When Vague Names Are OK

- **Container name provides full context**:
  ```python
  class User(BaseModel):
      id: int        # OK: obviously user's ID
      name: str      # OK: obviously user's name
  ```

- **Standard conventions** (e.g., `id` in Django/SQLAlchemy models as primary key)

- **Single entity of its type in scope**:
  ```python
  def process_task(task: Task, cfg: OptimizerConfig):  # OK: only one config
      cfg.validate()
  ```

- **Temporary variables** with short lifetime:
  ```python
  for key, value in items:  # OK: loop variable, short scope
      ...
  ```

- **Vague type compensated by good documentation**:
  ```python
  def parse_strategy(strategy: str) -> Strategy:
      """Parse strategy string.

      Args:
          strategy: Strategy name in format "provider:model" (e.g., "openai:gpt-4")
      """
      # OK: Documentation explains the string format/interpretation
  ```

## Benefits

✅ **Self-documenting** - No need to read docs/comments
✅ **Searchable** - `cache_key` is easier to grep than `key`
✅ **Less ambiguity** - Clear what the field represents
✅ **Better autocomplete** - More specific names group logically

## Examples from rspcache

```python
# ✗ BAD: Renamed from vague name
key: str  # What kind of key?

# ✓ GOOD: Explicit
cache_key: str  # SHA256 hash of request body
api_key: APIKeyModel | None  # Client API key for authentication
response_id: str | None  # OpenAI's response ID (e.g., 'resp_abc123')
```

## References

- [Google Python Style Guide - Naming](https://google.github.io/styleguide/pyguide.html#s3.16-naming)
- [PEP 8 - Descriptive Naming Styles](https://peps.python.org/pep-0008/#descriptive-naming-styles)
