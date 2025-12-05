local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Both `_commit_immediately()` and `_run_editor_flow()` end by calling `git commit`
    with similar passthru argument handling. The commit logic is duplicated when it
    should be factored out into a shared helper.

    **Problems:**

    1. **Code duplication**: Both functions filter passthru, spawn subprocess, wait for exit
    2. **Different interfaces**: One uses `-m msg`, other uses `-F path`, but both commit
    3. **Coupled logic**: Both must know about `filter_commit_passthru` and `--no-verify`
    4. **Maintenance burden**: Changes to commit invocation must be duplicated
    5. **Unclear separation**: Functions mix message preparation with commit execution

    **The correct approach:**

    Refactor into two helpers: `_prepare_commit_message()` (handles accept-AI vs editor
    flow, returns final message string) and `_execute_commit(message, passthru)` (filters
    passthru, spawns `git commit -m`, returns exit code). Main logic becomes: prepare
    message → execute commit.

    **Benefits:**

    1. **Single responsibility**: Message preparation separate from commit execution
    2. **No duplication**: Commit subprocess logic defined once
    3. **Easier testing**: Can test message validation independently
    4. **Clearer flow**: Main logic shows sequential steps explicitly
    5. **Easier changes**: Modify commit flags/behavior in one place
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [558, 564],  // _commit_immediately: duplicates commit execution
      [611, 615],  // _run_editor_flow: duplicates commit execution
    ],
  },
)
