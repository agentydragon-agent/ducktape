local I = import '../../lib.libsonnet';


I.issue(
  expect_caught_from=[
    ['adgn/src/adgn/agent/approvals.py'],
    ['adgn/src/adgn/agent/persist/sqlite.py'],
  ],
  rationale=|||
    Line 153 initializes `_policy_id: int = 1`. Line 175 in `set_policy()` just increments
    `self._policy_id += 1` without calling persistence, creating an invented in-memory counter
    that diverges from actual database IDs.

    The persistence layer (sqlite.py:198-217) marks existing ACTIVE policy as SUPERSEDED, creates
    new ACTIVE policy, and returns the database-assigned ID. But `set_policy()` never calls it,
    so `_policy_id` becomes an arbitrary counter unrelated to actual persisted policy IDs.

    Scenario: Load policy ID 5 from database via `load_policy()`, then call `set_policy()` twice.
    Result: `_policy_id` becomes 7 (5+1+1), but database has actual IDs 6 and 7. Logs/traces/MCP
    resources show mismatched IDs, breaking data integrity.

    Make `set_policy` async, call `await self.persistence.set_policy(...)`, and store the returned
    actual database ID in `_policy_id`. This ensures consistency: every component uses the same ID
    for the same policy.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [150, 153],  // Comments and _policy_id initialization
      [172, 180],  // set_policy incrementing instead of persisting
      [183, 186],  // load_policy (does use actual ID - correct)
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [198, 217],  // Persistence set_policy that returns ACTUAL ID
    ],
  },
)
