local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Debug log message uses manual string formatting instead of Python 3.8+ f-string debug syntax. The {var=} syntax is more concise and includes both variable name and value automatically.

    Current: f"Wrote event to DB: transcript_id={self.transcript_id}, seq={self._sequence_num - 1}, type={event_type}"

    Better: f"Wrote event to DB: {self.transcript_id=} {self._sequence_num - 1=} {event_type=}"
  |||,
  filesToRanges={'adgn/src/adgn/agent/db_event_handler.py': [68]},
)
