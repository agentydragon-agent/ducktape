local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 658-662 in agent.py define an async context manager that does nothing. The `__aenter__` method
    simply returns self, and `__aexit__` returns None without performing any cleanup or resource management.
    This implementation serves no purpose and should be removed. If callers currently use the context manager,
    they should be updated to instantiate the agent directly without the async with statement.
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [[658, 662]]},
)
