local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Docstring mentions specific use cases (critic/grader) when the functionality is generic and works for any transcript-based agent run. This misleads readers into thinking the handler is specialized when it's actually general-purpose.

    The transcript_id parameter links events to any agent run, not just critic/grader runs. The documentation should reflect this generality.
  |||,
  filesToRanges={'adgn/src/adgn/agent/db_event_handler.py': [38]},
)
