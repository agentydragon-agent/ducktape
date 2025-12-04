local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Functions inconsistently mix two conventions for signaling exit codes: some declare
    `-> int` return types but actually raise `ExitWithCode` exceptions on error paths.

    **Evidence:**
    - `_commit_immediately` (lines 558-564): declared `-> int`, but raises `ExitWithCode(1)` on some paths
    - `_run_editor_flow` (lines 567-609): declared `-> int`, but has 7 paths that raise `ExitWithCode`
    - Callers (lines 728-732): expect int return, but `sys.exit(code)` is unreachable when exception raised

    **Problems:**
    1. Type lies: functions promise `-> int` but raise exceptions, violating contracts
    2. Unreachable code: code after exception-raising calls never executes
    3. Easy to forget: callers must remember BOTH to check returns AND catch exceptions
    4. No guidance: new code has no clear pattern to follow

    **Fix:** Pick ONE convention consistently. Option A (always raise exceptions, change
    signatures to `-> None`): impossible to forget, clear failure paths, consistent with
    Python's `SystemExit`. Option B (always return int): never raise, always return codes.
    Mixing both violates type contracts and creates ad-hoc error handling.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [551, 556],  // ExitWithCode class with TODO about approach
      [558, 564],  // _commit_immediately: -> int but raises ExitWithCode
      [567, 609],  // _run_editor_flow: -> int but raises ExitWithCode (7 times)
      [728, 732],  // Callers expecting int, unreachable sys.exit() after exception paths
    ],
  },
)
