local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Global PersistentShell singleton breaks session isolation and creates hard-to-reason-about shared state.

    Summary
    - A process‑wide singleton shell (sync.Once) carries cwd/env/blockers across tool runs.
    - New callers mutate the same global instance (SetWorkingDir, SetBlockFuncs), so one session's state leaks into another.
    - This design prevents per‑session invariants and makes concurrency behavior unpredictable.

    Risks
    - Cross‑session leakage of working directory and environment.
    - Order‑dependent and racy behavior when multiple sessions/tools run concurrently.
    - Tests and real sessions can interfere with each other via shared global state.

    Acceptance criteria
    - Remove the global singleton; inject a per‑session Shell (or factory) via dependencies.
    - Tools (e.g., Bash) receive their own shell instance; no package‑level mutable state.
    - Concurrency tests demonstrate isolation (no shared cwd/env/blockers across sessions).
  |||,
  filesToRanges={
    'internal/shell/persistent.go': [[13, 36]],     // singleton definition + GetPersistentShell
    'internal/llm/tools/bash.go': [[314, 322]],     // GetPersistentShell + mutation via SetWorkingDir/SetBlockFuncs
  },
  expect_caught_from=[['internal/shell/persistent.go'], ['internal/llm/tools/bash.go']],
)
