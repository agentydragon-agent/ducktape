local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 105-115 return `"unknown"` when no server matches the URI. This is error-prone.

    **Current:**
    ```python
    async def _derive_server(self, uri: str) -> str:
        # ... try to find matching server ...
        for name in sorted(specs.keys()):
            name_str = str(name)
            if has_resource_prefix(uri, name_str, fmt):
                return name_str
        return "unknown"
    ```

    **Problem:** Returning a fabricated string `"unknown"` that:
    1. Callers might not handle specially
    2. Could be used as an actual server name downstream
    3. Fails silently instead of loudly
    4. Makes bugs harder to track (error happens far from source)

    **Fix:**
    ```python
    async def _derive_server(self, uri: str) -> str:
        # ... try to find matching server ...
        for name in sorted(specs.keys()):
            name_str = str(name)
            if has_resource_prefix(uri, name_str, fmt):
                return name_str

        # No server found - fail loudly
        raise ValueError(
            f"Could not derive server for URI {uri!r}. "
            f"Available servers: {sorted(specs.keys())}"
        )
    ```

    **Benefits:**
    1. Fail fast and loud
    2. Clear error message with context
    3. Forces caller to handle error case
    4. No silent corruption with fake "unknown" server name
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [105, 115],  // Returns "unknown" instead of raising exception
    ],
  },
)
