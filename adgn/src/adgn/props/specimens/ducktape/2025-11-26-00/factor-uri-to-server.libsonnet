local I = import '../../lib.libsonnet';

// iss-060: Factor out URI-to-server translation, check if FastMCP has it

I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/mcp/resources/server.py'],
    ['adgn/src/adgn/mcp/notifications/buffer.py'],
  ],
  rationale=|||
    Multiple locations loop through mount names to translate a resource URI back to
    its origin server name. This should be factored out and potentially already exists
    in FastMCP.

    **Pattern found in multiple places:**
    ```python
    origin: str | None = None
    for mn in mount_names:
        if has_resource_prefix(uri_str, mn, compositor.resource_prefix_format):
            origin = mn
            break
    ```

    **Similar logic also in:**
    - `_derive_server()` (buffer.py:105-115) - already documented in issue 056
    - Other locations using `has_resource_prefix()` in loops

    **Problems:**
    1. Code duplication - same pattern repeated multiple times
    2. Might already exist in FastMCP's proxy mounting implementation
    3. Error handling differs across call sites (None vs "unknown" vs exception)
    4. Not DRY

    **Correct approach:**
    Create a `derive_origin_server(uri, mount_names, prefix_format)` helper that:
    1. Loops through sorted mount names checking `has_resource_prefix(uri, name, prefix_format)`
    2. Returns the first matching server name
    3. Accepts optional `raise_on_unknown` parameter for flexible error handling (default True)
    4. Raises ValueError with available servers list if no match found and raise requested
    5. Returns None if no match and raise_on_unknown=False

    Place in `adgn/mcp/compositor/helpers.py` and replace all manual loops with calls to this
    function. This centralizes the logic and ensures consistent error handling across call sites.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/resources/server.py': [
      [355, 360],  // URI-to-server translation loop in list_resources_combined
    ],
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [105, 115],  // _derive_server - similar pattern
    ],
  },
)
