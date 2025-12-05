local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 36-37 in transcript_handler.py create the parent directory in `__init__`, which performs I/O
    during object construction. The comment on line 36 ("Create parent directory if needed") and the mkdir
    operation should be moved to `_write_event()` where the file is actually written. This follows the
    principle of lazy initialization and reduces work done during object construction. The mkdir call can
    be performed once before the first write operation.
  |||,
  filesToRanges={'adgn/src/adgn/agent/transcript_handler.py': [[36, 37]]},
)
