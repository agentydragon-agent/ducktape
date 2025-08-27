---
title: Try/except is scoped around the operation it guards
kind: outcome
---

Try/except blocks are short and localized: the try encloses only the minimal risky operation, with the except immediately following it. Treat exceptions as normal control flow guards (like `if`), not as wrappers for large bodies. Only top‑level error boundaries may use broad, larger try/except blocks with clear justification and logging.

## Scope
Applies only to agent‑added or agent‑edited hunks.

## Acceptance criteria (checklist)
- The `try` block encloses the minimal risky expression(s) (typically 1–3 lines); avoid wrapping long blocks of unrelated work
- Prefer `try/except/else` to keep the main logic outside the `try` when helpful
- Use specific, expected exception types (e.g., `json.JSONDecodeError`), not blanket catches, except at top‑level boundaries
- Separate independent risky operations into separate `try/except` blocks rather than one large wrapper
- Exception (allowed): At true outer boundaries (HTTP handler, main loop, task runner), a broader `try/except` may be used with a comment explaining the boundary and with full logging

## Positive examples
```python
# Parse JSON line: try encloses only the risky parse
async def _process_buffer_lines(self, buffer: str) -> None:
    lines = buffer.split("\n")
    for line in lines[:-1]:
        line = line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(
                "Malformed record",
                preview=line[:100],
                error=str(e),
            )
            await self._attempt_recovery(line)
            continue  # Early bailout
        # Normal path after successful parse
        if (event_id := payload.get("id")) in self._callbacks:
            callback = self._callbacks[event_id]
            callback(payload)
        else:
            logger.debug(
                "Received event",
                kind=payload.get("type"),
            )
```

```python
# Separate risky operations into distinct try/except blocks
from pathlib import Path

def read_config(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Config is not valid JSON", path=str(path), error=str(e))
        raise
```

### Error-boundary example (allowed)
```python
# Broad try/except at an HTTP boundary: log and return 500
def handle_request(req) -> Response:
    try:
        data = get_bytes()
        obj = json.loads(data)
        return make_response(obj)
    except Exception:
        logger.exception("Unhandled error in request handler")
        return Response(status=500)
```

## Negative examples
```python
# Too-wide try/except wraps long body — should scope around json.loads and early-bailout
async def _process_records(self, text: str) -> None:
    lines = text.split("\n")
    for record in lines[:-1]:
        record = record.strip()
        if not record:
            continue

        try:
            # Risky operation mixed with unrelated logic (too large try)
            obj = json.loads(record)
            logger.debug("Parsed object", id=obj.get("id"))
            if (eid := obj.get("id")) in self._callbacks:
                cb = self._callbacks[eid]
                cb(obj)
            else:
                logger.debug("Unrouted event", kind=obj.get("type"))
        except json.JSONDecodeError as e:
            logger.warning("Malformed record", preview=record[:100], error=str(e))
            await self._attempt_recovery(record)
```

```python
# One big try for unrelated risks in non-boundary code — should split into separate localized try/except blocks
try:
    blob = get_bytes()            # may raise TimeoutError
    obj = json.loads(blob)        # may raise JSONDecodeError
    write(obj)                    # may raise OSError
except Exception:                 # wrong here: not at a boundary and hides errors
    on_error()
```

```python
# Top-level else wrapping long body — exceptions used as a giant wrapper
try:
    verify()
except InvalidState:
    return failure()
else:
    # 20+ lines of main logic here — should move the main logic out, keep try minimal
    return build_result()
```
