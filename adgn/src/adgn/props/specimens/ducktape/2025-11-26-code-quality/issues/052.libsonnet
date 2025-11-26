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

    **For DisplayEventsHandler:** This handler just logs/displays events. It likely
    doesn't need to be first - it doesn't modify state or make decisions. It's
    probably fine to just append() instead of insert(0).

    **Investigation needed:**
    1. Check if handler order matters for the agent framework
    2. If DisplayEventsHandler doesn't need to be first, use append()
    3. If some handlers DO need specific ordering, document why

    **Likely fix:**
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
