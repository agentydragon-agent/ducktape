local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 532-536 define `_stage_all_if_requested()` which takes a boolean and is
    a no-op if the boolean is False. This is an antipattern.

    **Current:**
    ```python
    def _stage_all_if_requested(repo: pygit2.Repository, include_all: bool) -> None:
        if include_all:
            # Stage tracked changes (approximate 'git add -u')
            repo.index.add_all()
            repo.index.write()

    # Later at line 728:
    _stage_all_if_requested(repo, include_all)
    ```

    **Why this is an antipattern:**
    1. Function exists only to wrap an if-statement
    2. Caller already has the boolean condition
    3. Adds indirection for no benefit
    4. Function name encodes the condition ("if_requested")

    **Fix:** Inline at call site (line 728):
    ```python
    if args.stage_all:
        repo.index.add_all()
        repo.index.write()
    ```

    Delete the function definition (lines 532-536).

    **Benefits:**
    1. Fewer functions to track
    2. Control flow is explicit at call site
    3. No need to pass boolean parameter
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [532, 536],  // Function definition - should be inlined
      728,  // Call site - replace with if statement
    ],
  },
)
