local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/mcp/resources/server.py'],
    ['adgn/src/adgn/mcp/notifications/buffer.py'],
  ],
  rationale=|||
    Multiple locations (server.py:355-360, buffer.py:105-115) loop through mount names to
    translate a resource URI back to its origin server name. This pattern is duplicated.

    **The pattern:** Loop through mount_names, check `has_resource_prefix(uri, mn, format)`,
    return first match. But error handling differs: some return None, some "unknown", some
    raise exceptions.

    **Problems:** Code duplication, inconsistent error handling, not DRY. This logic might
    already exist in FastMCP's proxy mounting implementation.

    **Fix:** Create `derive_origin_server(uri, mount_names, prefix_format, raise_on_unknown=True)`
    helper in `compositor/helpers.py`. Returns first matching server name, raises ValueError
    with available servers if no match (when raise_on_unknown=True), or returns None otherwise.
    Replace all manual loops with calls to this function for centralized logic and consistent
    error handling.
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
