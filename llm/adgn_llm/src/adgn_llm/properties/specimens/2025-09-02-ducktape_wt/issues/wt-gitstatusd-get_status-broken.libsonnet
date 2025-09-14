local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    get_status uses a non-existent helper and magic tuple indices that don’t match any real
    return shape.

    Observed:
    - get_status() calls get_comprehensive_status() and then returns
        (comprehensive[0], comprehensive[1], comprehensive[5], comprehensive[6]).
      However, there is no get_comprehensive_status defined here.
    - The only nearby helper with a similar role is _update_comprehensive_cache(), which returns a
      4‑tuple (dirty_files, untracked_files, last_updated_at, is_dirty). Indexing [5], [6] is thus
      inconsistent even if the call target were corrected.

    Why this is bad:
    - Calling a non-existent method will fail at runtime.
    - Relying on hard-coded numeric indices against an unclear/unstable tuple shape is brittle and
      error-prone (“grab 6+ items and pull out 4”).

    Agnostic fix guidance (do not reintroduce magic indices):
    - Call a real, correctly-shaped provider of the needed status, and return the intended four
      values in a clear, self-documenting way.
    - Prefer a typed object (dataclass/Pydantic) or named fields over positional tuple slicing, so
      consumers access fields by name and can’t silently drift.
    - Alternatively, reimplement get_status without any “comprehensive” helper: compute the four
      required outputs directly (e.g., by querying gitstatusd or cached status) and return a typed
      object or explicit tuple in one place; avoid intermediate 6+ element tuples entirely.
    - Or derive the four outputs from the existing StatusResponse: use named counts/flags to compute
      booleans and timestamps, and map to a small StatusSummary type. This avoids any shape coupling
      to internal helpers.
  |||,
  filesToRanges={
    'wt/wt/server/wt_server.py': [[796, 806], [803, 810]],
  },
)
