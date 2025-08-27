---
title: Imports at the top
kind: outcome
---

All imports appear at the top of the module (not inside functions/classes); the only exception is a localized import used to break an otherwise unavoidable import cycle and must be documented with an inline comment.

## Scope
Applies only to agent‑added or agent‑edited hunks. Pre‑existing imports inside functions outside those edits do not count toward violations.

## Acceptance criteria (checklist)
- No `import` or `from ... import ...` statements inside functions, methods, or class bodies
- Module-level imports are grouped at the top (after optional shebang/encoding line and module docstring)
- The only permitted in-function imports are narrowly justified cases and must include an inline comment explaining the reason: breaking an import cycle; dynamic runtime import by string (plugin discovery, `module:function` resolution) or hot-reload; or truly excessive import cost that would unacceptably degrade startup time

- Dynamic imports via `__import__` and `importlib.import_module` follow the same restriction; they are not allowed inside functions unless one of the allowed exceptions applies

## Positive examples
```python
"""Module docstring."""
from __future__ import annotations

import json
from pathlib import Path

def load_config(p: Path) -> dict:
    text = p.read_text()
    return json.loads(text)
```

## Negative examples
```python
def load_config(p):
    import json  # ❌ inline import (not a cycle)
    return json.loads(p.read_text())
```

```python
# ❌ import placed after executable code
print("starting up")
import logging
```

## Exceptions (narrow, justified)

Import cycle (documented):
```python
def handler():
    # Allowed only to break an import cycle with foo.bar.handler
    # (module-level import would create a circular dependency)
    from foo.bar import handler as upstream_handler  # cycle-break exception
    return upstream_handler()
```

Dynamic plugin or entrypoint import by string:
```python
from importlib import import_module

def load_plugin(entrypoint: str):
    # Allowed: runtime plugin resolution "module.sub:factory"
    module_name, func_name = entrypoint.rsplit(":", 1)
    return getattr(import_module(module_name), func_name)
```

Hot reload during development:
```python
import importlib

def reload_config():
    # Allowed: hot reload for live config changes
    import myapp.config as config  # hot-reload context
    importlib.reload(config)
```

Deferring an excessively heavy import:
```python
def run_gpu_job():
    # Allowed: defer truly heavy import (e.g., 30s CUDA kernel compile at import time)
    import gigantic_cuda_lib  # heavy import justified
    return gigantic_cuda_lib.run()
```

## Additional negative examples
```python
def run_task(name: str):
    mod = __import__(name)  # ❌ dynamic import in function without justified exception
    return mod.run()
```

```python
from importlib import import_module

def run_task(name: str):
    mod = import_module(name)  # ❌ no plugin architecture/justification
    return mod.run()
```

Misleading justification (still a violation):
```python
def compute_now():
    # avoid import loop
    import datetime
    return datetime.datetime.now()
```