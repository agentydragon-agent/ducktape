local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 86-97 contain a verbose if-elif-else chain mapping ApprovalOutcome enum values
    to ApprovalStatus enum values with identical names (APPROVED→APPROVED, REJECTED→REJECTED,
    DENIED→DENIED, ABORTED→ABORTED).

    This identity mapping (same name → same name) suggests either: (1) unify the enums if
    they represent the same concept (see finding 024 for similar issue), or (2) use
    value-based conversion: `ApprovalStatus(record.decision.outcome.value)` with try/except,
    or (3) use a dict mapping if enums must remain separate.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/servers/approvals_bridge.py': [
      [86, 97], // if-elif-else chain for ApprovalOutcome to ApprovalStatus mapping
    ],
  },
)
