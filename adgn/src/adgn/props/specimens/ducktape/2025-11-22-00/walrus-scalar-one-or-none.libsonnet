local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Code uses assign-then-check pattern with `.scalar_one_or_none()` where walrus
    operator (:=) would be more concise.

    **Pattern:**
    ```python
    policy = result.scalar_one_or_none()
    if not policy:
        return None
    # use policy
    ```

    This assign-then-check pattern appears in multiple SQLAlchemy query methods.

    **Correct approach using walrus operator:**
    ```python
    if not (policy := result.scalar_one_or_none()):
        return None
    # use policy
    ```

    **Benefits:**
    - More concise (combines assignment and check)
    - Clearer scope (variable exists only where needed)
    - Standard Python 3.8+ idiom for "get and check" patterns
    - Reduces one-off temporary variables
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [263, 264], // policy = ...; if not policy (should walrus)
      [401, 402], // run = ...; if not run (should walrus)
    ],
  },
)
