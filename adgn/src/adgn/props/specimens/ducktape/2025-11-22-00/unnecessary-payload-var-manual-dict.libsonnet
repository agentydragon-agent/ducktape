local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Unnecessary intermediate variable for dict that's used only once, combined with
    manual dict construction from Pydantic model instead of using `model_dump()`.

    **Current code (container.py:52):**
    ```python
    payload = {"name": policy_input.name, "arguments": policy_input.arguments}
    # ... later used once
    ```

    Two problems:
    1. `payload` variable is only used once (no benefit to naming it)
    2. Manually constructing dict from Pydantic model fields instead of `model_dump()`

    **Correct approach:**

    Inline and use `model_dump()` with field selection:
    ```python
    # Inline directly where used
    ... policy_input.model_dump(include={"name", "arguments"}) ...
    ```

    **Benefits:**
    - One fewer variable
    - Pydantic handles serialization (respects aliases, validators, etc.)
    - More maintainable (if model fields change, dump adapts)
    - Explicit about which fields are serialized
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [52, 52],  // Unnecessary payload variable and manual dict construction
    ],
  },
)
