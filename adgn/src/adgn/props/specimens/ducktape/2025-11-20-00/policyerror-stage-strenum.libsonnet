local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    PolicyError.stage uses Literal["read", "parse", "tests"] instead of StrEnum
    for consistency with the rest of the codebase.

    Same file already uses StrEnum for PolicyErrorCode (lines 9-11), creating
    inconsistency. For fixed string sets with semantic meaning, StrEnum is
    preferred over Literal because it provides IDE autocomplete, type checking,
    refactoring support, and runtime validation.

    Should define PolicyErrorStage as StrEnum with READ/PARSE/TESTS members.

    Deeper question: Should stage field exist at all? PolicyErrorCode already
    captures error type (READ_ERROR, PARSE_ERROR). If stage is always derivable
    from code, it's redundant.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/models/policy_error.py': [15],
  },
)
