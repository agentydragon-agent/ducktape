local I = import '../lib.libsonnet';

// iss-020: Deprecated datetime.utcnow() usage

I.issue(
  snapshot='ducktape/2025-11-22-00',
  rationale= |||
    The code uses `datetime.utcnow()` to generate timestamps, but this function is
    deprecated as of Python 3.12 in favor of `datetime.now(timezone.utc)`.

    **Current implementation (transcript_handler.py, lines 45, 52):**
    ```python
    # Line 45:
    json.dumps({"started": datetime.utcnow().isoformat() + "Z"}, indent=2)

    # Line 52:
    out = {"ts": datetime.utcnow().isoformat() + "Z", **rec}
    ```

    **Problems:**

    1. **Deprecated**: `datetime.utcnow()` is deprecated in Python 3.12+
    2. **Naive datetime**: Returns a timezone-naive datetime object, requiring manual "Z" suffix
    3. **Error-prone**: Easy to forget the "Z" suffix or use wrong timezone
    4. **Inconsistent**: Mix of naive datetime + manual suffix instead of timezone-aware
    5. **Future incompatibility**: Will be removed in future Python versions

    **Python 3.12 deprecation warning:**
    ```
    DeprecationWarning: datetime.utcnow() is deprecated and scheduled for removal in
    a future version. Use timezone-aware objects to represent datetimes in UTC:
    datetime.now(timezone.utc).
    ```

    **The correct approach:**

    Use `datetime.now(timezone.utc)` which returns a timezone-aware datetime:

    ```python
    from datetime import datetime, timezone

    # Line 45:
    json.dumps({"started": datetime.now(timezone.utc).isoformat()}, indent=2)

    # Line 52:
    out = {"ts": datetime.now(timezone.utc).isoformat(), **rec}
    ```

    **Benefits:**

    1. **Not deprecated**: Uses the recommended Python 3.12+ API
    2. **Timezone-aware**: Returns datetime with UTC timezone information
    3. **Automatic formatting**: `.isoformat()` includes timezone offset automatically
       (e.g., `2024-01-15T10:30:00+00:00`)
    4. **No manual suffix**: No need to append "Z"
    5. **Type-safe**: Datetime knows it's UTC, not just a naive timestamp
    6. **Future-proof**: Won't break in future Python versions

    **Note on ISO format:**

    Both approaches produce valid ISO 8601 timestamps, but the timezone-aware version
    is more explicit:
    - Naive + "Z": `2024-01-15T10:30:00.123456Z`
    - Aware: `2024-01-15T10:30:00.123456+00:00`

    If you need the "Z" format specifically, you can convert:
    ```python
    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ```

    But the `+00:00` format is equally valid and more explicit about timezone.

    **Related deprecated functions:**

    - `datetime.utcnow()` → `datetime.now(timezone.utc)`
    - `datetime.utcfromtimestamp(ts)` → `datetime.fromtimestamp(ts, tz=timezone.utc)`
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/transcript_handler.py': [
      [45, 45],   // datetime.utcnow() in metadata timestamp
      [52, 52],   // datetime.utcnow() in event timestamp
    ],
  },
)
