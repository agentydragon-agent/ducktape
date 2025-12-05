local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Code explicitly calls .value on StrEnum instances, but StrEnum automatically
    coerces to its string value in string contexts.

    Pattern like PolicyStatus.ACTIVE.value in WHERE clauses is unnecessary
    verbosity. Should use PolicyStatus.ACTIVE directly in SQLAlchemy comparisons
    and assignments.

    Benefits:
    - Cleaner code: leverages StrEnum design
    - Type safety: keeps enum type longer in data flow
    - Refactoring support: easier to rename enum members
  |||,
  occurrences=[
    {
      note: 'Multiple .value calls on PolicyStatus and ApprovalStatus enums in SQLAlchemy queries and assignments',
      files: {
        'adgn/src/adgn/agent/persist/sqlite.py': [
          192,  // .value call
          207,  // .value call
          208,  // .value call
          213,  // .value call
          301,  // .value call
          302,  // .value call
          306,  // .value call
          342,  // .value call
          356,  // .value call
          381,  // .value call
        ],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/sqlite.py']],
    },
    {
      note: '.value call on StrEnum in history module',
      files: {
        'adgn/src/adgn/agent/server/history.py': [36],
      },
      expect_caught_from: [['adgn/src/adgn/agent/server/history.py']],
    },
  ],
)
