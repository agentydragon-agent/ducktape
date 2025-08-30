---
title: Use StrEnum for string‑valued enums (Python)
kind: outcome
---

Python enums with string values are declared with `enum.StrEnum` (Python 3.11+) rather than `class X(str, Enum)` or plain `Enum` with string literals.

## Acceptance criteria (checklist)
- String‑valued enums subclass `enum.StrEnum`
- Do not declare string enums as `class X(str, Enum)`
- Do not use plain `Enum` with string literal members when a string enum is intended
- Targeting older Python (<3.11) is an acceptable exception only when positively identified as the target

## Positive examples
```python
from enum import StrEnum

class ErrorCode(StrEnum):
    PROCESS_DIED = "process_died"
    COMMUNICATION_FAILURE = "communication_failure"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    STARTUP_FAILURE = "startup_failure"
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    UNKNOWN = "unknown"
```

## Negative examples
```python
# Old style — forbidden when targeting 3.11+
from enum import Enum

class ErrorCode(str, Enum):
    PROCESS_DIED = "process_died"
    COMMUNICATION_FAILURE = "communication_failure"
```

```python
# Plain Enum with string values — ambiguous intent
from enum import Enum

class ErrorCode(Enum):
    PROCESS_DIED = "process_died"
    COMMUNICATION_FAILURE = "communication_failure"
```