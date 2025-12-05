local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 620-621 in agent.py contain a useless fast-path return that checks if there are pending
    function calls before iterating and emitting results. This check doesn't provide any performance
    benefit since the following loop (lines 622-624) would naturally be a no-op if the list is empty.
    The early return adds unnecessary code without improving performance or clarity.
  |||,
  filesToRanges={'adgn/src/adgn/agent/agent.py': [[620, 621]]},
)
