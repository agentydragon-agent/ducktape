local I = import '../../specimens/lib.libsonnet';

// iss-052: Check if handlers.insert(0, ...) actually needs to be first

I.issueOneOccurrence(
  rationale=|||
    Two locations insert handlers at position 0 (front of list). Check if these
    actually need to be first or if order doesn't matter.

    **Occurrences:**
    1. `minicodex_backend.py:190` - DisplayEventsHandler inserted at start if debug
    2. `per_file_eval.py:225` - DisplayEventsHandler inserted at start

    **Question:** Do these handlers need to be first, or is the order arbitrary?

    **Verified:**
    `DisplayEventsHandler` (adgn/src/adgn/agent/event_renderer.py:19) is a pure observer -
    only prints events, doesn't modify state or make decisions. It has no side effects that
    other handlers depend on, so order doesn't matter.

    Line 187 context: `handlers = [CommitController(...)]` then optionally inserts
    DisplayEventsHandler at position 0 if debug enabled. CommitController handles actual
    logic; DisplayEventsHandler just logs.

    **Correct approach:**
    ```python
    # Instead of:
    handlers.insert(0, DisplayEventsHandler(...))

    # Use:
    handlers.append(DisplayEventsHandler(...))
    ```

    Unless there's a specific reason for front-of-list insertion, append() is clearer
    (handlers are processed in order added).
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      190,  // handlers.insert(0, DisplayEventsHandler)
    ],
    'adgn/src/adgn/props/per_file_eval.py': [
      225,  // handlers_list.insert(0, DisplayEventsHandler)
    ],
  },
)
