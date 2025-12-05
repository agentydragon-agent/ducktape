local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 80 does `json.loads(...)` to parse JSON, then passes the dict to `PolicyResponse.model_validate(data)`. Pydantic provides `model_validate_json()` which does both steps in one call and is more efficient.

    **Benefits of model_validate_json():**
    - Pydantic's JSON parser is faster (uses Rust)
    - Works directly on bytes (no decode needed for success case)
    - One-step parsing and validation
    - Better error messages from Pydantic

    **Correct approach:**

    Use `model_validate_json()` directly on bytes:
    ```python
    logs = container.logs(stdout=True, stderr=True) or b""
    if status != 0:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
    try:
        return PolicyResponse.model_validate_json(logs.strip())
    except Exception as e:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    ```
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [[76, 83]],
  },
)
