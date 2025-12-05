local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 560-568 define `ExitWithCode` exception for signaling exit codes. Python
    already has `SystemExit` built-in which serves exactly this purpose.

    **Current:**
    ```python
    class ExitWithCode(Exception):
        def __init__(self, code: int):
            super().__init__(str(code))
            self.code = code

    raise ExitWithCode(128)
    # Later caught: except ExitWithCode as e: sys.exit(e.code)
    ```

    **Standard approach:**
    ```python
    raise SystemExit(128)
    # SystemExit automatically exits with the code; no catch needed
    ```

    **Fix:**
    - Delete `ExitWithCode` class definition
    - Replace all `raise ExitWithCode(N)` with `raise SystemExit(N)`
    - Remove the `except ExitWithCode` handler in `main()` - SystemExit exits automatically
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [560, 568],  // Custom exception - use stdlib SystemExit instead
      [781, 784],  // Exception handler - not needed with SystemExit
    ],
  },
)
