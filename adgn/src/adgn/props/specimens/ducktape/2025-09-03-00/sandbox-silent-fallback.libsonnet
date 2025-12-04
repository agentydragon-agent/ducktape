local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The helper `_run_in_sandbox` (and the public `run_in_sandbox` wrapper) claim to run commands in a sandbox, but on non-Linux systems or when bubblewrap (bwrap) is missing they silently fall back to running the command unsandboxed.

    This is misleading and a security risk: callers and reviewers expect a function named "run_in_sandbox" to provide sandboxing guarantees. Silently weakening that guarantee (returning results from an unsandboxed execution) can lead to code that assumes isolation when none exists.

    Two safe remediation paths:
      1) Enforce sandboxing strictly: if the platform or dependencies (bwrap) do not support sandboxing, fail loudly (raise/exit) so callers must opt into unsandboxed behavior explicitly.
      2) Or make the contract explicit by renaming the function to indicate the behavior (e.g., `run_with_optional_sandbox`) and documenting the conditions under which sandboxing is unavailable; prefer an explicit opt-in for unsandboxed dev-mode.

    Prefer failing loudly when security is expected; silent fallbacks lead to subtle and dangerous bugs.

    The implementation is in local_tools.py (_run_in_sandbox, lines 49-56) and the public wrapper is in cli.py (run_in_sandbox, lines 124-133).
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py': [[49, 56]],
    'llm/adgn_llm/src/adgn_llm/mini_codex/cli.py': [[124, 133]],
  },
  expect_caught_from=[
    ['llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py'],
  ],
)
