local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The `_run_impl` method has a return type of `-> None` and contains two explicit `return` statements that should be removed:

    **Line 215**: Plain `return` after the try/except/finally block. Since the function returns `None`, this explicit return is unnecessary - the function will implicitly return None when it reaches the end.

    **Line 218**: Plain `return` at the very end of the method after the error logging. This is redundant since Python functions implicitly return None at the end.

    Unnecessary return statements add visual noise without providing value. In functions that return `None`, only early returns (to exit the function before reaching the end) are meaningful.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [[215, 215]]},
      note: 'Unnecessary return after try/except/finally in if branch',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [[218, 218]]},
      note: 'Unnecessary return at end of method',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
  ],
)
