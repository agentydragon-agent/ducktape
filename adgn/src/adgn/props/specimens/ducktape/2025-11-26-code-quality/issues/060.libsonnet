local I = import '../../specimens/lib.libsonnet';

// iss-060: Factor out URI-to-server translation, check if FastMCP has it

I.issueOneOccurrence(
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

    **Investigation needed:**
    1. Search FastMCP's proxy mounting implementation for URI-to-server translation
    2. Check if `compositor` has a method like `derive_server_from_uri()` or similar
    3. If FastMCP has it, use that instead
    4. If not, create a centralized helper function

    **Proposed fix (if FastMCP doesn't have it):**
    ```python
    def derive_origin_server(
        uri: str,
        mount_names: Iterable[str],
        prefix_format: str,
        *,
        raise_on_unknown: bool = True
    ) -> str | None:
        """Derive origin server name from resource URI.

        Args:
            uri: Resource URI to translate
            mount_names: Available mount names to check
            prefix_format: Resource prefix format from compositor
            raise_on_unknown: If True, raise ValueError when no match found

        Returns:
            Origin server name, or None if not found and raise_on_unknown=False

        Raises:
            ValueError: If no server matches and raise_on_unknown=True
        """
        for name in sorted(mount_names):
            if has_resource_prefix(uri, name, prefix_format):
                return name

        if raise_on_unknown:
            raise ValueError(
                f"Could not derive origin server for URI {uri!r}. "
                f"Available servers: {sorted(mount_names)}"
            )
        return None
    ```

    **Then replace all occurrences with calls to this function.**

    **If FastMCP has it:** Just use FastMCP's method everywhere.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/resources/server.py': [
      // Location TBD - need to find exact line numbers
    ],
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [105, 115],  // _derive_server - similar pattern
    ],
  },
)
