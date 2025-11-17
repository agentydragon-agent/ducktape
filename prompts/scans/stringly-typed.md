# Scan: Stringly-Typed Code

## Context
@../shared-context.md

## Overview

**"Strings are evil"** - Prefer `StrEnum` (or library-provided enums) over raw strings for categorical values.

Many libraries (OpenAI SDK, etc.) follow this pattern - USE THEIR ENUMS instead of strings.

## Pattern: String Literals Instead of Enums

### Generic Example

```python
# BAD: Stringly-typed
class Request(BaseModel):
    status: str  # What are valid values? Runtime errors on typos!

def process(request: Request):
    if request.status == "complet":  # Typo! Runtime error
        ...

# GOOD: Use StrEnum
class RequestStatus(StrEnum):
    QUEUED = "queued"
    COMPLETE = "complete"
    ERROR = "error"

class Request(BaseModel):
    status: RequestStatus  # Type-safe, autocomplete works

def process(request: Request):
    if request.status == RequestStatus.COMPLETE:  # ✓ Type-checked
        ...
```

### Using Library Enums

```python
# BAD: Re-implementing what library provides
class ModelType(StrEnum):
    GPT_4 = "gpt-4"
    GPT_4_TURBO = "gpt-4-turbo"

# GOOD: Use library's enum (if it exists)
from openai.types import ChatModel  # Example - check if this exists

# BAD: Using strings for well-known values
status_code: str = "success"  # What are valid values?
error_type: str = "validation_error"  # Easy to typo

# GOOD: Use enums from library
from http import HTTPStatus
status_code: HTTPStatus = HTTPStatus.OK

from openai import OpenAIError
# SDK often has error type enums - use them!
```

## Detection

### Quick Manual Patterns

```bash
# Find string fields that should be enums (common patterns)
rg --type py ": str.*#.*(status|type|kind|mode|state)"

# Find string literals in comparisons (might indicate enum candidates)
rg --type py '== "(queued|pending|complete|completed|error|success|failed|failure|skipped|cancelled|canceled|in_progress|processing)"'

# Find string status values in function/method calls
rg --type py 'status\s*=\s*"(queued|pending|complete|completed|error|success|failed|failure|skipped|cancelled|canceled|in_progress|processing)"'

# Find Literal types with multiple options (convert to StrEnum)
rg --type py 'Literal\[.*,.*\]'

# Look for repeated string patterns in code - when you see the same string values
# appearing multiple times, that's a strong signal for enum extraction:
# 1. Find existing enums, then search for string comparisons with those values
# 2. Look for status-like field names with string assignments
# 3. Check if codebase uses certain status values repeatedly

# Example: If you found a Status enum with COMPLETED/SKIPPED values,
# search for places still using strings:
#   rg --type py 'status.*=.*"(completed|skipped)"'
#   rg --type py '== "(completed|skipped)"'
#
# The key is to let the codebase guide you - find what enums exist,
# then search for string literals that should use those enums.
```

### Detection Strategy

**Primary Method**: Manual code reading - understand the domain, look for repeated categorical strings. Read code to understand which strings represent categorical values vs messages/IDs/etc.

**Automated Preprocessing** (discovers candidates, NOT definitive):

1. **String Literal Repetition Counter** (AST-based)
   - Walk AST extracting Constant nodes with string values
   - Filter: 3-30 chars, alphanumeric (skip URLs/paths/messages)
   - Count occurrences, report strings appearing 5+ times
   - Strong LLM can build from description

2. **String Comparison Detector** (AST-based)
   - Find Compare nodes with Eq operator + string literals
   - Group by compared values
   - Shows which strings are used in conditionals

3. **Categorical Field Analyzer** (AST-based)
   - Find AnnAssign nodes where field name contains: "status", "type", "kind", "mode", "state", "level"
   - Check if annotated as `str`
   - These fields are prime enum candidates

4. **Cross-Reference Existing Enums**
```bash
# Find enums already defined
rg --type py "class \w+\(.*Enum\):" -A5

# For each enum value, search for string literal usage
# If Status has COMPLETED = "completed", search for "completed" strings
rg --type py '"completed"' --glob '!**/enums.py'
```

5. **Assignment Pattern Analysis**
```bash
# Count status/type assignments to find common values
rg --type py "(status|type|kind|mode|state)\s*=\s*\"([^\"]+)\"" -o | sort | uniq -c | sort -rn
```

**Critical Workflow**:
1. Run automated tools → get candidate strings
2. **MANUALLY READ CODE** - understand domain, group related values
3. Determine if candidates are truly categorical (not messages/IDs)
4. Create enums for related value groups
5. Search codebase for specific enum values to replace

**Warning**: Automated tools are preprocessing only. String "error" appears everywhere - manual judgment determines if it's an enum candidate or just a message.

## Fix Strategy

1. **Check library first**:
   - Does OpenAI SDK / library already have the enum?
   - Use `from openai.types import X` instead of reinventing
   - READ THE ACTUAL SOURCE CODE of the library types

2. **Create StrEnum for internal values**:
   ```python
   from enum import StrEnum

   class MyStatus(StrEnum):
       QUEUED = "queued"
       COMPLETE = "complete"
   ```

3. **Replace string fields**:
   ```python
   # Before
   status: str

   # After
   status: MyStatus
   ```

4. **Update comparisons**:
   ```python
   # Before
   if status == "complete":

   # After
   if status == MyStatus.COMPLETE:
   ```

5. **Serialization handled automatically**:
   - Pydantic serializes `StrEnum` to string in JSON
   - Deserializes string back to `StrEnum`
   - Use `@field_serializer` if you need `.value`

## Benefits

✅ **Type safety** - Typos caught at type-check time, not runtime
✅ **Autocomplete** - IDE shows all valid values
✅ **Documentation** - Enum definition documents all possible values
✅ **Refactoring** - Rename enum value, all usages update
✅ **Exhaustiveness** - Type checker ensures you handle all cases

## Examples from rspcache

```python
# ✓ GOOD: Using StrEnum for internal status
class ResponseStatus(StrEnum):
    COMPLETE = "complete"
    ERROR = "error"

# ✓ GOOD: Using library types
from openai.types.responses import (
    Response as OpenAIResponse,
    ResponseUsage,
    ResponseError,
)

# TODO: Check if OpenAI SDK has status enums we should use
```

## Pattern: Unstructured Error Messages

Error reason/message fields storing free-form strings should use structured types:

```python
# BAD: Free-form error strings
class Response(BaseModel):
    status_reason: str | None = None  # Could be anything!

# Usage scattered across codebase:
status_reason = "Streaming proxy failure"
status_reason = str(exc)  # Exception message
status_reason = f"Upstream status {resp.status_code}"
status_reason = "Upstream returned non-JSON response"

# GOOD: Structured error with StrEnum
class ProxyErrorType(StrEnum):
    UPSTREAM_HTTP = "upstream_http"
    STREAMING_FAILURE = "streaming_failure"
    REQUEST_EXCEPTION = "request_exception"
    INVALID_RESPONSE = "invalid_response"

class ProxyError(BaseModel):
    type: ProxyErrorType
    message: str
    detail: dict[str, Any] | None = None

class Response(BaseModel):
    error: ProxyError | None = None

# BETTER: Tagged union for type-specific fields
class UpstreamHttpError(BaseModel):
    type: Literal["upstream_http"]
    status_code: int
    response_body: str | None = None

class StreamingFailure(BaseModel):
    type: Literal["streaming_failure"]
    exception_message: str

ProxyError = UpstreamHttpError | StreamingFailure | ...
```

**Why structured errors?**
- Categorize errors for metrics/alerting
- Type-safe error handling
- Extract structured info (status codes, etc.)
- Query/filter errors in DB by type

## Common Enum-Worthy Patterns

These string patterns often indicate enum candidates:

- **Status/State**: `"pending"`, `"active"`, `"completed"`, `"failed"`
- **Type/Kind**: `"user"`, `"admin"`, `"system"`
- **Mode**: `"readonly"`, `"readwrite"`, `"admin"`
- **Level**: `"debug"`, `"info"`, `"warning"`, `"error"`
- **Direction**: `"inbound"`, `"outbound"`
- **Format**: `"json"`, `"xml"`, `"csv"`
- **Error reasons**: Multiple different error messages → categorize with enum

## References

- [Python StrEnum docs](https://docs.python.org/3/library/enum.html#enum.StrEnum)
- [Stringly-typed (Martin Fowler)](https://martinfowler.com/bliki/StringlyTyped.html)
- [Pydantic Enums](https://docs.pydantic.dev/latest/concepts/types/#enums)
