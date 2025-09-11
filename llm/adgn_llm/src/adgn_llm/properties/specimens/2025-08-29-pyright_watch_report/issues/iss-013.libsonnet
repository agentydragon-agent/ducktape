local obj = {
  id: "iss-013",
  should_flag: true,
  rationale: |||
    Use collections.Counter for tallying exclude-pattern hits.

    The code currently initializes a mapping of exclude pattern -> 0 and increments counts imperatively. Using collections.Counter makes intent clearer, avoids the manual zero-initialization, and expresses that this object is for counting/histogram purposes.

    Before (excerpt):

    ```python
    # pyright_watch_report.py:
    exclude_hits: dict[str, int] = dict.fromkeys(exclude, 0)
    ...
    for pat in exclude:
        if matches_any(rp, [pat]):
            exclude_hits[pat] += 1
    ```

    After (recommended):

    ```python
    from collections import Counter
    exclude_hits = Counter()
    ...
    exclude_hits.update(pat for pat in exclude if matches_any(rp, [pat]))
    ```

    Counter saves the initialization/default-to-zero and documents intent (counts/histogram) succinctly.
  |||,
  properties: [],
  instances: [
    { files: { "pyright_watch_report.py": [ { start_line: 104, end_line: 105 } ] } },
    { files: { "pyright_watch_report.py": [ { start_line: 134, end_line: 139 } ] } },
  ],
};

obj
