local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `calculate_cost()` function in `cost.py` duplicates logic that already exists in the database `run_costs` view and is never called.

    All cost calculations in the codebase are performed by the database view (defined in `src/adgn/props/db/models.py:588-636`), which:
    - Aggregates token usage from the `events` table
    - Joins with `model_pricing` table for current rates
    - Computes costs using the same formula as this function
    - Is queried by `BudgetEnforcementHandler` via `po_run_costs()` query builder

    The Python function has no callers anywhere in the codebase. It appears to be either early prototype code that was superseded by the database approach, or documentation/reference code that was never meant to be called.

    Keeping both implementations creates:
    - Duplication risk: changes to pricing logic must be made in two places
    - Inconsistency risk: implementations could drift apart
    - Maintenance burden: extra file to maintain and understand

    The database view is the single source of truth and should remain so.
  |||,
  filesToRanges={
    'adgn/src/adgn/openai_utils/cost.py': [[13, 42]],
  },
)
