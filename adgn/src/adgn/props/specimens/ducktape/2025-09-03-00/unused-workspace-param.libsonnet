local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The helper `_write_sandboxed_kernelspec(run_root: Path, workspace: Path, policy_yaml: Path, kernel_python: str, *, trace: bool)` declares a `workspace` parameter that is not used in the function body.

    Unused parameters add cognitive overhead and misleading API surface. Remove the unused parameter (or use it if there is a real need) to tighten the function signature and reduce confusion.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[192, 208]],
  },
)
