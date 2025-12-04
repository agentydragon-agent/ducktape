local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    AgentContainer.close() deconstructs CloseResult to rebuild identical dict
    (registry.py:43-44):

    result = await self.running.close()  # Returns CloseResult
    return {"drained": result.drained, "error": result.error}

    CloseResult is a dataclass with drained and error fields (running.py:28-31).
    The code extracts these fields to create a dict with the same structure.

    Should return the result directly:
    return await self.running.close()

    Or inline the call:
    await self.runtime.close()
    return await self.running.close()

    Benefits:
    - No useless reconstruction
    - Preserves type information (CloseResult vs untyped dict)
    - Clearer intent: propagate result from running.close()
    - Less code

    Investigation shows return value unused at call site (registry.py:105),
    so dict reconstruction serves no purpose. If serialization needed, use
    dataclasses.asdict() or Pydantic.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [
      [43, 44],     // result extraction and dict reconstruction
    ],
  },
)
