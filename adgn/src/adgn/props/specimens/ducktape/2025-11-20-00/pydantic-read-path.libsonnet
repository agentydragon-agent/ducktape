local I = import '../../lib.libsonnet';

// Related issue: pydantic-write-path.libsonnet (output side of persistence boundary handling)

I.issue(
  rationale= |||
    Building intermediate dict before constructing Pydantic model at read boundary.

    Code creates row_dict from SQLAlchemy result (lines 445-454), then passes to
    parse_event. This intermediate dict step is unnecessary and loses type safety.

    Should construct EventRecord directly with keyword arguments for immediate field
    validation and type checking.

    Anti-pattern: dict as intermediate representation when going from DB row to
    typed model. Correct approach: pass SQLAlchemy row fields directly to Pydantic
    constructor using keyword arguments.

    Benefits:
    - Type safety: catch field mismatches at type-check time
    - No intermediate dict allocation
    - Immediate validation on construction
    - Clearer data flow
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [[445, 454]],
  },
)
