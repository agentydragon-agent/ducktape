local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Uses `handlers.insert(0, DisplayEventsHandler(...))` to prepend the handler, but
    this is unnecessary because DisplayEventsHandler is a pure observer with no ordering
    requirements.

    **Analysis:**
    `DisplayEventsHandler` (adgn/src/adgn/agent/event_renderer.py:19) only prints events
    and doesn't modify state or make decisions. It has no side effects that other handlers
    depend on, so order doesn't matter.

    In minicodex_backend.py line 187 context: `handlers = [CommitController(...)]` then
    optionally inserts DisplayEventsHandler at start if debug enabled. CommitController
    handles actual logic; DisplayEventsHandler just logs.

    **Correct approach:**
    Replace `handlers.insert(0, DisplayEventsHandler(...))` with
    `handlers.append(DisplayEventsHandler(...))` since order doesn't matter and append
    is clearer (handlers are processed in order added).
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      190,  // handlers.insert(0, DisplayEventsHandler)
    ],
  },
)
