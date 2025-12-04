local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `last_event_at` field in agents_ws.py is typed as `str | None` but should be `datetime | None`.
    The field is later converted to ISO string for JSON serialization (line 81), which is
    the correct place to do that conversion.

    **Current:**
    ```python
    last_event_at: str | None = None  # Line 73
    ...
    last_event_at=last.isoformat() if last else None,  # Line 81
    ```

    The field stores an ISO string, but semantically it represents a timestamp. Better to
    store as datetime and convert during serialization.

    **Better:**
    ```python
    last_event_at: datetime | None = None
    ...
    last_event_at=last.isoformat() if last else None,  // Conversion happens here
    ```

    **Benefits:**
    - Type accurately represents semantic meaning
    - Can do datetime operations on the field if needed
    - Conversion to string happens at serialization boundary
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/agents_ws.py': [
      [73, 73],  // last_event_at: str | None = None
      [81, 81],  // .isoformat() conversion site
    ],
  },
)
