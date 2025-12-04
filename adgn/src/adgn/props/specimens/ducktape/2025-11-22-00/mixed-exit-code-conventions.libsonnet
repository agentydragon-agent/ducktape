local I = import '../../lib.libsonnet';

// iss-012: Mixed conventions for signaling exit codes

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    Functions inconsistently mix two conventions for signaling exit codes: some
    functions declare `-> int` return types but actually raise `ExitWithCode`
    exceptions on error paths. This creates type lies and makes it easy to forget
    error handling.

    **Current implementation shows mixed patterns:**

    ```python
    # Pattern 1: Declared to return int, but raises exceptions on some paths
    async def _commit_immediately(msg: str, passthru: list[str]) -> int:
        if not msg.strip():
            raise ExitWithCode(1)  # ❌ Type says returns int, actually raises
        commit_proc = await asyncio.create_subprocess_exec(...)
        return await commit_proc.wait()  # ✓ Returns int

    async def _run_editor_flow(...) -> int:
        # Declared -> int, but has 7 paths that raise ExitWithCode instead
        # (lines 587, 596, 599, 609, 665, 694)
        if error_condition:
            raise ExitWithCode(1)  # ❌ Type says returns int
        ...
    ```

    **Callers don't know whether to expect int or exception:**
    ```python
    # In async_main():
    if args.accept_ai:
        code = await _commit_immediately(msg, passthru)  # Expects int...
        sys.exit(code)  # ... but this line is unreachable if exception raised!
    ```

    **Problems:**

    1. **Type lies**: Functions promise `-> int` but raise exceptions, violating contracts
    2. **Unreachable code**: Code after exception-raising calls never executes
    3. **Easy to forget**: Callers must remember BOTH to check returns AND catch exceptions
    4. **No guidance**: New code has no clear pattern to follow
    5. **Fragile**: Adding new error paths requires remembering which convention to use

    **The correct approach:**

    Pick ONE convention and use it consistently everywhere:

    **Option A: Always raise exceptions (recommended):**
    ```python
    # Change signatures to not promise int:
    async def _commit_immediately(msg: str, passthru: list[str]) -> None:
        if not msg.strip():
            raise ExitWithCode(1)
        commit_proc = await asyncio.create_subprocess_exec(...)
        code = await commit_proc.wait()
        if code != 0:
            raise ExitWithCode(code)
        # Success: no return

    # Caller handles uniformly:
    try:
        if args.accept_ai:
            await _commit_immediately(msg, passthru)
        else:
            await _run_editor_flow(...)
        # Implicit success = exit 0
    except ExitWithCode as e:
        sys.exit(e.code)
    ```

    **Option B: Always return int:**
    ```python
    # Never raise ExitWithCode, always return:
    async def _commit_immediately(msg: str, passthru: list[str]) -> int:
        if not msg.strip():
            return 1  # Don't raise, return
        commit_proc = await asyncio.create_subprocess_exec(...)
        return await commit_proc.wait()

    # Caller:
    code = (await _commit_immediately(...) if args.accept_ai
            else await _run_editor_flow(...))
    sys.exit(code)
    ```

    **Why Option A (exceptions) is better:**

    1. **Impossible to forget**: Exceptions force handling (or crash)
    2. **Clear failure paths**: Exceptions make errors explicit
    3. **No silent bugs**: Can't accidentally ignore a return code
    4. **Consistent with Python**: `SystemExit` is exception-based
    5. **Type-safe**: `-> None` doesn't promise a return value

    **Why mixing is wrong:**

    1. Function signatures lie about their behavior
    2. Type checkers can't catch the inconsistency
    3. Callers must know implementation details (does it return or raise?)
    4. Error handling becomes ad-hoc and incomplete
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
