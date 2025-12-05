local I = import '../../lib.libsonnet';

// Docstrings duplicate information already present in type system

I.issueMulti(
  rationale=|||
    Docstrings duplicate information already present in type system, creating
    maintenance burden without adding information.

    Problems with redundant docstrings:
    - Create desync risk when types change
    - Duplicate maintenance (must update multiple locations)
    - Violate DRY principle
    - Add no information beyond type definitions

    Correct approach: Document types at their definition sites. Functions/models
    using those types should reference the type name, not duplicate its documentation.
  |||,
  occurrences=[
    {
      note: 'reduce_ui_state docstring lists all accepted event types with descriptions, duplicating the UiStateEvent union definition at line 33',
      files: {
        'adgn/src/adgn/agent/server/reducer.py': [[46, 52]],
      },
      expect_caught_from: [['adgn/src/adgn/agent/server/reducer.py']],
    },
    {
      note: 'Policy model docstring documents PolicyStatus enum states (ACTIVE/PROPOSED/REJECTED/SUPERSEDED) which should only exist on the PolicyStatus StrEnum definition',
      files: {
        'adgn/src/adgn/agent/persist/models.py': [[135, 145]],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
  ],
)
