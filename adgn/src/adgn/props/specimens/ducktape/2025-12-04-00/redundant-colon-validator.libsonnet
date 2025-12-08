local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 31-36 define `_reject_colon` validator that rejects colons in BaseIssueID values. However, this validator is redundant because the pattern constraint on line 44 already excludes colons.

    The pattern `r"^[a-z0-9_-]+$"` only allows lowercase letters, digits, underscores, and hyphens. Colons are not in this character class, so any string containing a colon will fail pattern validation before reaching the `BeforeValidator(_reject_colon)` on line 45.

    The validator function and its usage should be deleted as they add no value beyond what the pattern already enforces.
  |||,
  filesToRanges={'adgn/src/adgn/props/ids.py': [[31, 36], 45]},
)
