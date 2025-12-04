local I = import '../../lib.libsonnet';

// iss-010: Redundant exception handler that only re-exits

I.issue(
  rationale= |||
    The top-level `async_main()` function has a try-except handler that catches
    `ExitWithCode` exceptions only to immediately call `sys.exit()` with the same
    code. This adds 4 lines and one indent level for no benefit.

    **Current implementation (cli.py, lines 659-734):**
    ```python
    async def async_main(argv: list[str] | None = None):
        try:
            # ... 70 lines of main logic indented one level ...

            if args.accept_ai:
                code = await _commit_immediately(msg, passthru)
                sys.exit(code)

            code = await _run_editor_flow(repo, msg, previous_message, stats_comment, passthru)
            sys.exit(code)
        except ExitWithCode as e:
            sys.exit(e.code)  # ❌ Just forwards to sys.exit - no transformation
    ```

    **Problems:**

    1. **Redundant indentation**: All 70+ lines of main logic are indented for no reason
    2. **No added value**: The handler doesn't transform, log, or enrich the exit code
    3. **Verbosity**: 4 extra lines (try, except, handler, extra blank line)
    4. **Misleading**: Suggests the handler does something special, but it doesn't

    **The correct approach:**

    Remove the try-except entirely. `ExitWithCode` exceptions can propagate to the
    top level (or be caught by asyncio.run()), and Python's default behavior will
    still terminate with the exit code.

    Or if you want to ensure clean exit:
    ```python
    async def async_main(argv: list[str] | None = None):
        # ... all the main logic, no extra indent ...

        if args.accept_ai:
            code = await _commit_immediately(msg, passthru)
            sys.exit(code)

        code = await _run_editor_flow(repo, msg, previous_message, stats_comment, passthru)
        sys.exit(code)
        # No try-except needed!
    ```

    **Benefits:**

    1. **Simpler**: 4 fewer lines, 70+ lines with one less indent
    2. **Clearer**: No false suggestion that exception handling adds logic
    3. **More readable**: Main logic not buried in a try block
    4. **Standard pattern**: Top-level functions typically don't catch their own exit exceptions

    **Note:** This is separate from issue 012 about mixed exit code conventions.
    This issue is specifically about the redundant handler that adds no value.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [660, 660],  // try: at start of async_main
      [733, 734],  // except ExitWithCode as e: sys.exit(e.code)
    ],
  },
)
