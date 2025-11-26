local I = import '../../specimens/lib.libsonnet';

// iss-053: Remove gateway_client param, inline res_server, delete useless comments

I.issueOneOccurrence(
  rationale=|||
    Lines 21-36 have multiple issues in `mount_standard_inproc_servers()`:

    **Issue 1: Useless comments (lines 29-30)**
    ```python
    # Note: gateway_client parameter is no longer used by make_resources_server
    # Resources server creates its own direct client to bypass policy gateway
    ```
    These comments document code history/internals that don't help readers. Delete them.

    **Issue 2: Unnecessary res_server variable (line 31)**
    ```python
    res_server = make_resources_server(name="resources", compositor=compositor)
    await compositor.mount_inproc("resources", res_server, pinned=True)
    ```
    Single-use variable - should inline into mount_inproc() call.

    **Issue 3: Unused gateway_client parameter (line 21)**
    The parameter is checked (`if gateway_client is not None`) but its value is never
    used. Comments say it's "no longer used". This is dead code.

    **Fix:**
    1. Delete useless comments (lines 29-30) about gateway_client parameter history
    2. Inline `res_server` variable - pass `make_resources_server(...)` directly to `mount_inproc()`
    3. Replace unused `gateway_client: Client | None = None` parameter with explicit
       `mount_resources: bool = True` to control whether resources server is mounted
    4. Update docstring to reflect the new parameter
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/compositor/setup.py': [
      21,  // gateway_client parameter - unused
      [29, 30],  // Useless comments
      31,  // res_server - should inline
    ],
  },
)
