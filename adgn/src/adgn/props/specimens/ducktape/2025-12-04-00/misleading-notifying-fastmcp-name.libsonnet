local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    `NotifyingFastMCP` inherits from `FlatModelFastMCP` (line 107 of notifying_fastmcp.py), bundling both notification support and flat model support into one class. However, the name "Notifying" only suggests the notification feature, hiding the fact that it also provides flat model tooling.

    This creates confusion when servers inherit from `NotifyingFastMCP` but don't use notifications - developers ask "what notifications are you emitting?" when the answer is often "none". Many MCP servers in the snapshot instantiate NotifyingFastMCP purely to get flat model support, not notification broadcasting:

    - `loop/server.py`: `mcp = NotifyingFastMCP(name, ...)` then only uses `@mcp.flat_model()`, no broadcast calls
    - `git_ro/server.py`: imports NotifyingFastMCP, never calls any broadcast_* methods
    - `exec/docker/server.py`: `server = NotifyingFastMCP(name, ...)` for container exec, no notifications

    Only `chat/server.py` and `matrix/server.py` actually use `broadcast_resource_updated()` for their intended purpose.

    The inheritance hierarchy creates false coupling between two independent features (notifications and flat model support) that should be composable separately.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifying_fastmcp.py': [[107, 107]],
    'adgn/src/adgn/mcp/loop/server.py': [[16, 16]],
    'adgn/src/adgn/mcp/git_ro/server.py': [[28, 28]],
    'adgn/src/adgn/mcp/exec/docker/server.py': [[18, 18]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/mcp/notifying_fastmcp.py'],
  ],
)
