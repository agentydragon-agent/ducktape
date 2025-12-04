local I = import '../../lib.libsonnet';

// Merged: walrus-cache-get, walrus-include-verbose, walrus-inline-checks, walrus-subprocess-rc
// All describe assign-and-check/assign-and-test patterns that should use walrus operator

I.issue(
  rationale= |||
    Multiple locations use assign-then-check patterns where the walrus operator (:=)
    would be more concise and idiomatic. Common patterns include:

    1. **Path existence check** (Cache.get pattern):
       path = self.dir / f"{key}.txt"
       return path.read_text() if path.exists() else None

       Should use: return (p.read_text() if (p := self.dir / f"{key}.txt").exists() else None)

    2. **Git config fallback** (bind-and-test):
       config_verbose = repo.config.get_bool("commit.verbose")
       include_verbose = config_verbose if config_verbose is not None else False

       Should use walrus in the conditional to bind and test in one place.

    3. **Subprocess return code checks**:
       rc = await proc.wait()
       if rc != 0:
           raise subprocess.CalledProcessError(rc, cmd)

       Should use: if (rc := await proc.wait()) != 0: raise ...

    4. **Editor/process return codes**:
       editor_proc = await create_subprocess_exec(...)
       rc = await editor_proc.wait()
       if rc != 0: ...

       Should inline with walrus: if (rc := await editor_proc.wait()) != 0: ...

    Benefits of walrus operator (PEP 572):
    - More concise: combines assignment and condition
    - Clearer intent: value is used once, in the test
    - Standard Python idiom for "bind and check" patterns
    - Variable scope is explicit (only exists where needed)
    - Reduces one-off temporary variables

    Note: Not applicable when the variable is used multiple times outside
    the conditional, or when it improves readability to keep them separate.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [
      [421, 429],     // git config fallback (include-verbose)
      [448, 451],     // Cache.get: path existence check
      [599, 606],     // subprocess returncode (pre-commit hook)
      [731, 739],     // git var GIT_EDITOR
      [894, 902],     // git commit -m path
      [927, 933],     // editor returncode
      [969, 976],     // git commit -F path
      [1044, 1052],   // Claude invocation
      [1149, 1154],   // Codex invocation
    ],
  },
)
