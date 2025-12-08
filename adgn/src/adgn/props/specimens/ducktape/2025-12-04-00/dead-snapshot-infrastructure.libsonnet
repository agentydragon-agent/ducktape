local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The `Snapshot` infrastructure is dead code left over from the WebSocket → MCP migration. Both the `Snapshot` class and the `build_snapshot()` method should be removed.

    **Snapshot class** (protocol.py lines 128-133): Pydantic model that was used to serialize snapshot data for the `/api/agents/{id}/snapshot` HTTP endpoint. The endpoint was removed in Phase 5c (commit d43292aa - "feat(adgn): implement Phase 5c REST API removal"). The class is no longer referenced anywhere except in dead code.

    **build_snapshot() method** (runtime.py lines 137-156): Method that constructs `Snapshot` objects. A ripgrep search shows no calls to this method anywhere in the codebase. The method was only used by the removed HTTP endpoint.

    Evidence of removal:
    - Comment at runtime.py:153 mentions "UI state updates now fetched via HTTP GET /api/agents/{id}/snapshot" but this endpoint no longer exists
    - Git history (commit d43292aa) shows the endpoint was removed along with other REST API routes
    - The UI no longer calls this endpoint (migrated to MCP)
    - No code paths call `build_snapshot()` or instantiate `Snapshot` objects (except the dead `build_snapshot()` itself)

    The `Snapshot` class also appears in the `ServerMessage` union at protocol.py:139 with comment "HTTP snapshot endpoint" but this is also dead - the union is only used by the reducer which doesn't handle `Snapshot` events.

    Note: `SamplingSnapshot` (from `adgn.mcp.snapshots`) is a different type and is still actively used. Only the protocol.py `Snapshot` type is dead.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/agent/server/protocol.py': [[128, 133]]},
      note: 'Snapshot class definition',
      expect_caught_from: [['adgn/src/adgn/agent/server/protocol.py']],
    },
    {
      files: {'adgn/src/adgn/agent/server/runtime.py': [[137, 156]]},
      note: 'build_snapshot() method that constructs dead Snapshot objects',
      expect_caught_from: [['adgn/src/adgn/agent/server/runtime.py']],
    },
  ],
)
