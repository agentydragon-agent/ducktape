local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The code calls `list(res.contents)` only to pass it to `_build_window_payload()`.
    This creates an unnecessary intermediate list when the function could accept any iterable.

    **Current pattern:**
    ```python
    res = await compositor_client.read_resource_mcp(uri_value)
    contents = list(res.contents)
    return _build_window_payload(contents, input.start_offset, None if input.max_bytes == 0 else input.max_bytes)
    ```

    **Function signature:**
    ```python
    def _build_window_payload(
        contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
        start_offset: int,
        max_bytes: int | None,
    ) -> ...
    ```

    **Problems:**
    1. Unnecessary intermediate variable `contents`
    2. Unnecessary `list()` conversion - creates copy of iterable
    3. Less readable - extra line for simple data transformation
    4. Type signature is too restrictive - should accept any `Sequence` or `Iterable`

    **Fix:** Update `_build_window_payload` to accept `Sequence` instead of `list`, then inline:
    ```python
    # Update function signature:
    def _build_window_payload(
        contents: Sequence[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
        start_offset: int,
        max_bytes: int | None,
    ) -> ...

    # Then inline at call site:
    res = await compositor_client.read_resource_mcp(uri_value)
    return _build_window_payload(res.contents, input.start_offset, None if input.max_bytes == 0 else input.max_bytes)
    ```

    **Benefits:**
    1. One less line of code
    2. No unnecessary list conversion
    3. More flexible - accepts any sequence type
    4. More readable - direct data flow

    **Alternative:** If `_build_window_payload` only needs iteration (not indexing), use `Iterable` instead
    of `Sequence`. Check the function body to determine which is appropriate.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/resources/server.py': [
      [385, 386],  // contents = list(res.contents) and call to _build_window_payload
      [191, 194],  // _build_window_payload function signature - should accept Sequence
    ],
  },
)
