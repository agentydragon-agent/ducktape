local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The CLI `main()` in `mcp/sandboxed_jupyter_mcp/cli.py` merely delegates to `wrapper.main()` without adding any value (no argument transformation, validation, or help text).
    One-line passthrough wrappers like this add indirection and lines of code for no benefit. Prefer calling the implementation directly from entry points or consolidating the tiny delegating main into the wrapper to reduce churn and improve readability.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/cli.py': [[6, 7]],
  },
)
