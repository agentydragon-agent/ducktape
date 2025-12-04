local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The wrapper contains a legacy PolicyConfig shim that exists only for import compatibility with older tests.
    Keeping dead shims because "tests still reference it" is not a sufficient reason to retain the code: tests should be updated to the canonical model or provided a test-only shim.

    Why this is bad:
    - It preserves dead/unused code paths that increase maintenance burden and cognitive load.
    - New readers assume the shim is live behavior and may write code to support it, increasing cruft.
    - Tests depending on obsolete shims should be migrated or wrapped in explicit test fixtures rather than perpetuating legacy surface area.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[23, 27]],
  },
)
