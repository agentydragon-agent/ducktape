local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Line 293 converts `rec.status` to `ProposalStatus` enum, suggesting the persistence
    layer and application layer use different types for the same concept.

    **The issue:** `PolicyProposal.status` (persist/__init__.py) is typed as `str`, not
    `ProposalStatus`. Line 293 must convert at the application boundary. This creates drift
    risk: invalid status strings in the database won't be caught by the type system, and
    runtime errors occur if the database contains unexpected values.

    **Fix:** Change `PolicyProposal.status` from `str` to `ProposalStatus` enum. Pydantic
    validates on construction. No conversion needed at line 293 - persistence layer enforces
    the enum, application layer receives typed values.

    Benefits: single source of truth, type safety throughout stack, no runtime conversion
    errors.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [293, 293],  // ProposalStatus(rec.status) conversion
    ],
  },
)
