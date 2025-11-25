local I = import '../../specimens/lib.libsonnet';

// iss-006: PolicyError.stage should be StrEnum (if field should exist at all)

I.issueOneOccurrence(
  rationale=|||
    PolicyError.stage uses Literal["read", "parse", "tests"] instead of StrEnum.

    Same file already uses StrEnum for PolicyErrorCode (lines 9-11), creating inconsistency.
    For fixed string sets with semantic meaning, StrEnum is preferred over Literal.

    StrEnum benefits:
    - IDE autocomplete and type checking
    - Refactoring support (rename across codebase)
    - Runtime validation (can't pass arbitrary string)
    - Consistent with PolicyErrorCode pattern in same file

    Should be:
    class PolicyErrorStage(StrEnum):
        READ = "read"
        PARSE = "parse"
        TESTS = "tests"

    Deeper question (per user): Should stage field exist at all?
    - PolicyErrorCode already captures error type (READ_ERROR, PARSE_ERROR)
    - If stage is always derivable from code, it's redundant
    - Consider removing if it doesn't provide independent information
  |||,
  properties=['python/strenum', 'consistent-naming-and-notation', 'type-correctness-and-specificity'],
  filesToRanges={
    'adgn/src/adgn/agent/models/policy_error.py': [
      15,           // stage: Literal["read", "parse", "tests"]
      [9, 11],      // PolicyErrorCode StrEnum (shows existing pattern)
    ],
  },
  gap_note=|||
    Field may be redundant if stage is always derivable from error code.
    Should evaluate if stage provides independent information or can be removed entirely.
  |||,
)
