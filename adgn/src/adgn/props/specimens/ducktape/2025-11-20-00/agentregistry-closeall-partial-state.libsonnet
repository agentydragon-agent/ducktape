local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    AgentRegistry.close_all() leaves the registry in a partially closed state if any
    AgentRuntime.close() raises. The method loops through _items and calls close() on each
    runtime sequentially without error handling (lines 103-105). If the first close() succeeds
    but the second raises, the first runtime is closed but the second and all remaining runtimes
    are left open. Additionally, the exception prevents reaching line 106's _items.clear(), so
    the registry continues holding references to all runtimes (both closed and unclosed). Later
    lookups via get_agent_runtime() return these stale references, mixing closed and open
    runtimes unpredictably.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [[102, 106]],
  },
)
