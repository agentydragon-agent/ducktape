local I = import '../../specimens/lib.libsonnet';

// iss-046: Should inline all_handlers in MiniCodex.create

I.issueOneOccurrence(
  rationale=|||
    Code creates all_handlers variable, used once immediately (local_runtime.py:123,144):

    all_handlers = list(handlers) + self._extra_handlers
    # ...
    agent = await MiniCodex.create(
        model=self.model,
        mcp_client=self.running.compositor_client,
        system=base_system,
        client=client,
        handlers=all_handlers,  # Only use
        ...
    )

    Should inline:
    agent = await MiniCodex.create(
        model=self.model,
        mcp_client=self.running.compositor_client,
        system=base_system,
        client=client,
        handlers=list(handlers) + self._extra_handlers,
        ...
    )

    Benefits:
    - Removes intermediate variable
    - Clearer: composition visible at use site
    - Less line count

    Note: base_system (line 129) is used twice (lines 142 and 152), so should
    NOT be inlined to avoid duplication or re-evaluation.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/runtime/local_runtime.py': [
      123,          // all_handlers = list(handlers) + self._extra_handlers
      144,          // handlers=all_handlers (only use)
    ],
  },
)
