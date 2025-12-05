local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/approvals.py'],
    ['adgn/src/adgn/mcp/approval_policy/server.py'],
    ['adgn/src/adgn/agent/mcp_bridge/server.py'],
    ['adgn/src/adgn/agent/mcp_bridge/servers/agents.py'],
  ],
  rationale=|||
    The notifier callback pattern across ApprovalHub, ApprovalPolicyEngine, AgentRegistry, and
    sessions has five design problems making it brittle:

    Problem 1: Single `_notifier` field replaced by `set_notifier()` supports only one listener
    at a time (not proper observer/pub-sub). Multiple consumers require manual wrappers.
    Examples: ApprovalHub._notifier (line 82), ApprovalPolicyEngine._notify (line 156).

    Problem 2: Notifiers typed as sync but documented "sync and non-blocking (may schedule async
    work)" (approvals.py:87, 165). AgentRegistry expects async, forcing `create_task()` wrappers
    (approval_policy/server.py:96-100).

    Problem 3: Fire-and-forget `create_task()` swallows or only logs exceptions (agents.py:844-851).
    approval_policy/server.py:100 accesses exception only to prevent asyncio warnings.

    Problem 4: Notifiers called without try/except (approvals.py:101-102, 109-110, 178-181). If
    notifier throws, crashes whole operation.

    Problem 5: Inconsistent patterns - some use `if self._notifier:`, others use intermediate `cb`
    variable (lines 204-206, 209-211) that's pointless.

    Replace with async observer pattern: list of async observers, `add_observer()` method,
    `_notify_observers()` that iterates with try/except per observer. Benefits: multiple observers,
    consistent async/await, explicit exception handling, type-safe.
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
