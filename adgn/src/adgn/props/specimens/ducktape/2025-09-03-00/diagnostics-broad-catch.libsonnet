local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    During diagnostics the code catches broad Exception, prints a diagnostic message, and continues. In a diagnostics path this masks failures that were supposed to surface useful debug information — the wrapper should fail fast or at least propagate the error after logging full context.

    Diagnostics code should make problems visible and actionable. Silently continuing after printing a short message prevents test harnesses and callers from noticing failures and makes root-cause debugging much harder.

    Prefer: log full traceback and re-raise (or exit non-zero) so CI/tests detect the issue. Only suppress known, explicitly documented non-fatal exceptions.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[343, 343]],
  },
)
