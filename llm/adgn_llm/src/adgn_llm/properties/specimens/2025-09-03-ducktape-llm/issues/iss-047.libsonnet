local I = import '../../specimen_issues.libsonnet';

// iss-047: Use walrus to bind and check subprocess return code; raise on failure
I.issueOneOccurrence(
  rationale= |||
    Several asyncio.create_subprocess_exec callers await/inspect return codes with extra variables or
    without a clear failure path. Prefer the walrus operator to bind and test in one line and raise on non‑zero,
    e.g.: `if (rc := await proc.wait()) != 0: raise subprocess.CalledProcessError(rc, cmd)`.

    Benefits:
    - Clear, fail‑loud error path for subprocess failures
    - Less boilerplate (bind+check in a single expression)
    - Consistent handling across all subprocess sites
  |||,
  properties=['walrus','early-bailout'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [599,606],   // pre-commit hook wrapper
      [731,739],   // git var GIT_EDITOR
      [894,902],   // git commit -m path
      [969,976],   // git commit -F path
      [1044,1052], // Claude invocation
      [1149,1154], // Codex invocation
    ],
  },
)
