---
title: Use pathlib for path manipulation
kind: outcome
---

Agent-edited Python uses pathlib for filesystem paths and joins; it does not use os.path.* or manual string concatenation for paths.

## Scope
Applies only to agent‑added or agent‑edited hunks. Pre‑existing legacy paths outside those edits do not count toward violations.

## Acceptance criteria (checklist)
- Paths are represented as `pathlib.Path` objects
- Path joins use `/` operator or `Path(..., ...)`, not `os.path.join`
- File I/O uses Path methods (`read_text`, `write_text`, `read_bytes`, `open`) instead of bare `open` on string paths
- No manual string concatenation for paths
- Function parameters/returns that represent filesystem paths use `pathlib.Path` (preferred) or `os.PathLike[str]` for interoperability

## Positive examples
```python
from pathlib import Path

base = Path(env_root) / "var" / "data"
config = base / "app.cfg"
text = config.read_text(encoding="utf-8")
```

```python
from pathlib import Path

outdir = Path(tmpdir)
(outdir / "report.json").write_text(payload, encoding="utf-8")
```

```python
# Function parameters typed as Path (preferred)
from pathlib import Path
import json

def read_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))

def write_report(out_dir: Path, name: str) -> Path:
    p = out_dir / f"{name}.json"
    p.write_text("{}", encoding="utf-8")
    return p
```

## Negative examples
```python
import os

base = os.path.join(env_root, "var", "data")
config = os.path.join(base, "app.cfg")
with open(config, encoding="utf-8") as f:
    text = f.read()
```

```python
# Manual concatenation — forbidden
logfile = env_root + "/logs/" + name + ".txt"
```