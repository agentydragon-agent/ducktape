local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 385-386 call `list(res.contents)` only to pass to `_build_window_payload()`. Creates unnecessary intermediate list and variable.

    Problems: (1) unnecessary `list()` conversion, (2) extra line for simple data transformation, (3) `_build_window_payload` signature (lines 191-194) too restrictive with `list` parameter type.

    Update `_build_window_payload` to accept `Sequence` instead of `list`, then inline at call site (pass `res.contents` directly). If function only needs iteration (not indexing), use `Iterable` instead of `Sequence`.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/resources/server.py': [
      [385, 386],  // contents = list(res.contents) and call to _build_window_payload
      [191, 194],  // _build_window_payload function signature - should accept Sequence
    ],
  },
)
