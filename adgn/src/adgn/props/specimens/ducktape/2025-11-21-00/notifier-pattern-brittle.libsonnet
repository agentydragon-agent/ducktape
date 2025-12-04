local I = import '../../lib.libsonnet';

// iss-037: Notifier pattern is brittle and has multiple design problems

I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/approvals.py'],
    ['adgn/src/adgn/mcp/approval_policy/server.py'],
    ['adgn/src/adgn/agent/mcp_bridge/server.py'],
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
  ],
  rationale=|||
    The notifier callback pattern (ApprovalHub, ApprovalPolicyEngine, AgentRegistry, sessions)
    has 5 design problems making it brittle:

    **Problem 1: 0-or-1 receivers, not N**

    Single notifier field (`_notifier`, `_notify`) replaced by `set_notifier()`. Only one listener
    at a time - not proper observer/pub-sub. Multiple consumers require manual wrapper functions.

    Examples: ApprovalHub._notifier (line 82), ApprovalPolicyEngine._notify (line 156),
    AgentRegistry._notifier (server.py:92).

    **Problem 2: Mixed sync/async with awkward contract**

    Notifiers typed as sync but documented "sync and non-blocking (may schedule async work)"
    (approvals.py:87, 165). AgentRegistry expects async. Forces `loop.create_task()` wrappers
    (approval_policy/server.py:96-100).

    **Problem 3: Exception swallowing**

    Fire-and-forget `create_task()` swallows or only logs exceptions (agents.py:844-851).
    Caller never knows if broadcast_resource_updated fails. approval_policy/server.py:100
    accesses exception only to prevent asyncio warnings - doesn't handle or log.

    **Problem 4: No exception handling at call sites**

    Notifiers called without try/except (approvals.py:101-102, 109-110, 178-181). If notifier
    throws, crashes whole operation.

    **Problem 5: Inconsistent patterns**

    Some use `if self._notifier:`, others use intermediate `cb` variable (lines 204-206, 209-211).
    Intermediate variable pointless.

    **Fix:**

    Replace with async observer pattern:

    ```python
    class ApprovalHub:
        def __init__(self):
            self._observers: list[Callable[[str], Awaitable[None]]] = []

        def add_observer(self, observer: Callable[[str], Awaitable[None]]) -> None:
            self._observers.append(observer)

        async def _notify_observers(self, uri: str) -> None:
            for observer in self._observers:
                try:
                    await observer(uri)
                except Exception as e:
                    logger.warning(f"Observer notification failed for {uri}: {e}", exc_info=True)
    ```

    **Benefits:** Multiple observers, granular URI notifications, consistent async/await,
    explicit exception handling per observer, type-safe.

    **Impact:** ApprovalHub (2 call sites), ApprovalPolicyEngine (5+ call sites), AgentRegistry
    (1 call site), session notifiers, wiring code (agents.py:833-932).
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [82, 82],    // ApprovalHub._notifier field
      [84, 89],    // set_notifier with "sync and non-blocking" contract
      [101, 102],  // Unguarded notifier call in await_decision
      [109, 110],  // Unguarded notifier call in resolve
      [156, 156],  // ApprovalPolicyEngine._notify field
      [162, 167],  // set_notifier with "sync and non-blocking" contract
      [178, 181],  // Unguarded notify calls
      [204, 206],  // Unnecessary intermediate cb variable pattern
      [209, 211],  // Unnecessary intermediate cb variable pattern
    ],
    'adgn/src/adgn/mcp/approval_policy/server.py': [
      [96, 100],   // Fire-and-forget notifier with exception swallowing
    ],
    'adgn/src/adgn/agent/mcp_bridge/server.py': [
      [87, 92],    // AgentRegistry.set_notifier (async variant)
      [182, 183],  // Unguarded notifier call
    ],
    'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [
      [844, 851],  // Fire-and-forget pattern with logged exceptions
      [870, 874],  // Fire-and-forget pattern with logged exceptions
      [890, 894],  // Fire-and-forget pattern with logged exceptions
      [907, 911],  // Fire-and-forget pattern with logged exceptions
    ],
  },
)
