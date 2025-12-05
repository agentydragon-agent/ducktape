local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 45 and 52 use `datetime.utcnow().isoformat() + "Z"` for timestamp generation.

    `datetime.utcnow()` is deprecated as of Python 3.12 (scheduled for removal in future versions).
    It returns a timezone-naive datetime, requiring manual "Z" suffix concatenation.

    Replace with `datetime.now(timezone.utc)` which returns a timezone-aware datetime. The `.isoformat()`
    call automatically includes timezone offset (e.g., `2024-01-15T10:30:00+00:00`), eliminating the
    manual suffix. If "Z" format is required, use `.replace("+00:00", "Z")`.

    Timezone-aware datetime provides type safety (datetime knows it's UTC, not just a naive timestamp)
    and prevents accidentally forgetting the timezone suffix or using the wrong timezone.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/transcript_handler.py': [
      [45, 45],   // datetime.utcnow() in metadata timestamp
      [52, 52],   // datetime.utcnow() in event timestamp
    ],
  },
)
