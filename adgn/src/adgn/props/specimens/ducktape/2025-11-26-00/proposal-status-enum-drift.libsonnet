local I = import '../lib.libsonnet';

// iss-010: ProposalStatus(rec.status) conversion suggests enum drift/duplication

I.issue(
  snapshot='ducktape/2025-11-26-00',
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

    **Root cause (verified):**
    The `PolicyProposal` model (adgn/src/adgn/agent/persist/__init__.py) has `status: str`,
    not `status: ProposalStatus`. The conversion `ProposalStatus(rec.status)` happens at
    the application boundary (line 293).

    This creates potential for:
    - Invalid status strings in database (not caught by type system)
    - Drift between valid database values and enum values
    - Runtime errors if database contains unexpected status strings

    **Correct approach:**
    Change `PolicyProposal.status` from `str` to `ProposalStatus` enum. Pydantic will
    automatically validate on construction. Then line 293 becomes:
    ```python
    ProposalRow(id=rec.id, status=rec.status, ...)  # Already ProposalStatus
    ```

    No conversion needed - persistence layer enforces the enum, application layer receives
    typed values.

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
