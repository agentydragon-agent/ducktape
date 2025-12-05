local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The field name `_events_path` is unnecessarily verbose. It should be shortened to `_path` since the
    context (TranscriptHandler that writes events) makes it clear what the path is for. The same applies
    to the `__init__` parameter `events_path`. Shorter names improve readability without losing clarity.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/transcript_handler.py': [
      34,  // __init__ parameter
      35,  // field assignment
      37,  // mkdir parent
      39,  // exists check
      40,  // FileExistsError
      47,  // open in _write_event
    ],
  },
)
