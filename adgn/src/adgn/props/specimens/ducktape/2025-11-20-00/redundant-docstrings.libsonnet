local I = import '../../lib.libsonnet';

// Extracted from redundant-documentation.libsonnet
// Kept only the docstring duplication issues (useless comment moved to separate file)

I.issue(
  snapshot='ducktape/2025-11-20-00',
  rationale= |||
    Docstrings duplicate information already present in type system, creating maintenance
    burden without adding information.

    **Two cases of redundant docstrings:**

    **1. reduce_ui_state docstring (reducer.py:46-52)**
    Lists all accepted event types with descriptions, duplicating the UiStateEvent union
    definition (reducer.py:33). If UiStateEvent changes, docstring may not update.
    Documentation should live at type definition sites, not duplicated in every function
    using the type.

    **2. Policy model docstring (models.py:135-145)**
    Documents PolicyStatus enum states (ACTIVE/PROPOSED/REJECTED/SUPERSEDED) which should
    only exist on the PolicyStatus StrEnum definition. Model docstrings should describe
    the model's purpose, not enumerate enum values.

    **Problems with redundant docstrings:**
    - Create desync risk when types change
    - Duplicate maintenance (must update multiple locations)
    - Violate DRY principle
    - Add no information beyond type definitions

    **Correct approach:**

    Document types at their definition sites. Functions/models using those types should
    reference the type name, not duplicate its documentation.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/reducer.py': [
      [46, 52],  // Docstring duplicating UiStateEvent union
    ],
    'adgn/src/adgn/agent/persist/models.py': [
      [135, 145],  // Docstring duplicating PolicyStatus enum
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/server/reducer.py'],
    ['adgn/src/adgn/agent/persist/models.py'],
  ],
)
