local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 188-189 define policy persistence methods with unclear return types:
    `get_latest_policy` returns `tuple[str, int] | None` where tuple unpacking
    requires remembering the order and the int's meaning (policy ID) is non-obvious.
    `set_policy` returns an undocumented int (the database-assigned policy ID).

    Problems: Tuple unpacking requires remembering element order, no semantic meaning
    to tuple positions, unclear what the int represents, requires checking None before
    unpacking, callers must know implementation details.

    Replace with a typed object (PolicyRecord or NamedTuple) containing id, content,
    timestamp, and agent_id fields. This provides self-documenting field names,
    type safety, IDE autocomplete, and clear semantics. Alternatively, at minimum
    add docstring documenting what the int represents.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/__init__.py': [
      188,
      189,
    ],
  },
)
