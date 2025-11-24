local I = import '../../specimens/lib.libsonnet';

// iss-018: Type confusion about run_id (UUID vs str)

I.issueOneOccurrence(
  rationale=|||
    Code inconsistently treats run_id as UUID in Python domain but str in persistence layer.

    Function signatures use UUID (append_event at sqlite.py:363: run_id: UUID),
    but immediately convert to str for database operations (sqlite.py:378: run_id=str(run_id)).

    Run.id is Mapped[str] in model (models.py:57), but domain code uses UUID.
    This creates constant str(run_id) conversions throughout persistence layer.

    Should pick one consistently:
    - Option A: Use UUID throughout, store as BLOB/UUID type in database
    - Option B: Use str in domain, remove UUID type from interfaces

    Preferred: Keep UUID in domain (stronger type), but model should handle conversion.
    SQLAlchemy supports UUID types that handle serialization automatically.

    Benefits of consistency:
    - No manual str() conversions
    - Type safety: can't mix run IDs with other strings
    - Clear boundary between domain (UUID) and storage (handled by ORM)

    Current state creates confusion: is run_id a UUID or string?
  |||,
  properties=['type-correctness-and-specificity', 'no-defensive-programming'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      57,           // Run.id: Mapped[str]
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      378,          // Event creation: run_id=str(run_id)
      389,          // WHERE Run.id == str(run_id)
    ],
  },
  gap_note=|||
    Should search for all str(run_id) conversions to document full extent. May affect
    other UUID-typed fields like agent_id.
  |||,
)
