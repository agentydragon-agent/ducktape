local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Function _abort_result has parameter with default value that is immediately replaced with another default in the function body. The DEFAULT_ABORT_ERROR constant should simply be the parameter default, eliminating the redundant `or` expression.

    Current pattern: `def _abort_result(reason: str | None = None) -> ...: return _make_error_result(reason or DEFAULT_ABORT_ERROR)`

    Should be: `def _abort_result(reason: str = DEFAULT_ABORT_ERROR) -> ...: return _make_error_result(reason)`
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [[139, 140]]},
)
