local I = import '../../lib.libsonnet';

I.issue(
  expect_caught_from=[['adgn/src/adgn/agent/approvals.py'], ['adgn/src/adgn/agent/persist/__init__.py']],
  rationale= |||
    Two overlapping enums exist: `ApprovalOutcome` (persist/__init__.py:36 with values like `POLICY_ALLOW`,
    `USER_APPROVE`, etc.) and `ApprovalStatus` (approvals.py:70-76 with values `PENDING`, `APPROVED`, `REJECTED`,
    etc.). Lines 175-181 define `map_outcome_to_status()` converter that tries `ApprovalStatus(outcome.value)`,
    catches ValueError, and returns `REJECTED` as fallback.

    Converter ALWAYS fails: tries to construct `ApprovalStatus("policy_allow")` which doesn't exist in enum,
    silently returns REJECTED for every input. This causes systematic information loss: `ApprovalOutcome`
    captures WHAT (allow/deny/abort) and WHO (POLICY_/USER_ prefix), but `ApprovalStatus` loses WHO information.
    Can't distinguish "policy auto-approved" from "user explicitly approved after review" - breaks audit trails,
    analytics, debugging, and compliance.

    Use single unified type preserving both outcome and source: either comprehensive enum with `POLICY_APPROVED`,
    `USER_APPROVED`, etc., or separate `Decision(outcome: DecisionOutcome, source: DecisionSource)` model.
    Eliminates need for converters with error-hiding fallbacks.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/approvals.py': [
      [70, 76],   // ApprovalStatus enum definition (loses source information)
      [175, 181], // map_outcome_to_status converter (always fails, silently returns REJECTED)
    ],
    'adgn/src/adgn/agent/persist/__init__.py': [
      [36, 42],   // ApprovalOutcome enum (preserves both outcome and source)
    ],
  },
)
