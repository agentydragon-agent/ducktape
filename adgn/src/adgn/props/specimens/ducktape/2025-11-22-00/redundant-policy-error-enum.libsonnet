local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 9-11 define `PolicyErrorCode` enum with `READ_ERROR` and `PARSE_ERROR` values. Lines 14-17
    define `PolicyErrorStage` enum with `READ`, `PARSE`, and `TESTS` values. Lines 21-22 in `PolicyError`
    model include both `stage: PolicyErrorStage` and `code: PolicyErrorCode` fields.

    These enums are redundant: error code is always stage + "_error" suffix. Having both requires
    keeping enums in sync when adding stages, creates confusing dual representation, and leaves TESTS
    stage without corresponding error code. PolicyError fields are redundant (code fully determined by stage).

    Keep only `PolicyErrorStage` enum. Remove `code` field from `PolicyError` model (lines 21-22) or
    add `@property def code()` that returns `f"{self.stage}_error"` for backwards compatibility. Alternatively,
    merge into single unified enum with `READ_ERROR`, `PARSE_ERROR`, `TESTS_ERROR` values. Eliminates
    duplication, easier maintenance, no mismatch risk, complete coverage.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/models/policy_error.py': [
      [9, 11],   // PolicyErrorCode enum (redundant)
      [14, 17],  // PolicyErrorStage enum
      [21, 22],  // PolicyError with both stage and code fields
    ],
  },
)
