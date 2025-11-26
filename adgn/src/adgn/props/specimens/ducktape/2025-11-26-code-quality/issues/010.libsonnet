local I = import '../../specimens/lib.libsonnet';

// iss-010: ProposalStatus(rec.status) conversion suggests enum drift/duplication

I.issueOneOccurrence(
  rationale= |||
    The code converts `rec.status` (from persistence) to `ProposalStatus` enum, which
    suggests there may be multiple versions of the same enum or semantic drift between
    the persistence layer and the application layer.

    **Current implementation (app.py:293):**
    ```python
    ProposalRow(
        id=rec.id, status=ProposalStatus(rec.status), created_at=rec.created_at, decided_at=rec.decided_at
    )
    ```

    **Problems:**
    1. `rec.status` comes from persistence as a string (or another enum)
    2. It's being converted to `ProposalStatus` enum
    3. This suggests the persistence layer and application layer use different types
    4. Multiple representations of the same concept = drift risk

    **Investigation needed:**
    - What type is `rec.status`? (likely `str` from database)
    - Is there a `PolicyProposal.status` field in the persistence models?
    - Does the Persistence protocol use a different enum?
    - Should the database return `ProposalStatus` directly?

    **Likely root cause:**
    The `PolicyProposal` model in persistence likely has `status: str`, and the
    conversion happens at the application boundary. This creates potential for:
    - Invalid status strings in database (not caught by type system)
    - Drift between valid database values and enum values
    - Runtime errors if database contains unexpected status strings

    **Correct approach:**
    1. Check if there's a persistence-layer status enum
    2. If yes: Ensure it's the same as `ProposalStatus` (no duplication)
    3. If no: Add validation at the persistence layer so it returns `ProposalStatus` directly
    4. Ideally: Store enum values in DB, parse to enum on read, so application layer always
       works with typed enums

    **Benefits:**
    1. Single source of truth for valid status values
    2. Type safety throughout the stack
    3. No runtime conversion errors
    4. Database constraints match application constraints
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [293, 293],  // ProposalStatus(rec.status) conversion
    ],
  },
)
