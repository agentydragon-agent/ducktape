local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Code explicitly calls .value on StrEnum instances throughout sqlite.py and
    history.py, but StrEnum automatically coerces to its string value in string
    contexts.

    Pattern like PolicyStatus.ACTIVE.value in WHERE clauses is unnecessary
    verbosity. Should use PolicyStatus.ACTIVE directly in SQLAlchemy comparisons
    and assignments.

    Benefits:
    - Cleaner code: leverages StrEnum design
    - Type safety: keeps enum type longer in data flow
    - Refactoring support: easier to rename enum members
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      192,
      207,
      208,
      213,
      301,
      302,
      306,
      342,
      356,
      381,
    ],
    'adgn/src/adgn/agent/server/history.py': [
      36,
    ],
  },
)
