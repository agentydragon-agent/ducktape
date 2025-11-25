local I = import '../../specimens/lib.libsonnet';

// iss-017: Should leverage StrEnum directly, not .value

I.issueOneOccurrence(
  rationale=|||
    Code explicitly calls .value on StrEnum instances, but StrEnum is designed to work
    directly as strings without .value calls.

    PolicyStatus, PersistenceRunStatus, and EventType are all StrEnum types.
    When used in string contexts (SQLAlchemy comparisons, assignments), StrEnum
    automatically coerces to its string value.

    Current pattern (sqlite.py:192):
    .where(Policy.status == PolicyStatus.ACTIVE.value)

    Should be:
    .where(Policy.status == PolicyStatus.ACTIVE)

    Same for assignments:
    status=PolicyStatus.ACTIVE.value  →  status=PolicyStatus.ACTIVE
    type=type.value  →  type=type

    Benefits of removing .value:
    - Cleaner code: leverages StrEnum design
    - Type safety: keeps enum type longer in data flow
    - Consistency: same pattern everywhere

    The .value calls are unnecessary verbosity that obscures the StrEnum type.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      192,          // PolicyStatus.ACTIVE.value in WHERE
      207,          // PolicyStatus.ACTIVE.value in WHERE
      208,          // PolicyStatus.SUPERSEDED.value in VALUES
      213,          // PolicyStatus.ACTIVE.value in constructor
      301,          // PolicyStatus.ACTIVE.value in WHERE
      302,          // PolicyStatus.SUPERSEDED.value in VALUES
      306,          // PolicyStatus.ACTIVE.value assignment
      342,          // PersistenceRunStatus.RUNNING.value in constructor
      356,          // status.value in VALUES (dynamic)
      381,          // type.value in constructor (dynamic)
    ],
    'adgn/src/adgn/agent/server/history.py': [
      36,           // ev.type.value
    ],
  },
)
