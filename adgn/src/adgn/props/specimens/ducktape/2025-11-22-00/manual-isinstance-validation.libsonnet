local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `reload()` method manually validates that the loaded JSON is a dict with string
    keys and values using `isinstance()` checks, but this can be done automatically and
    more robustly using Pydantic's `TypeAdapter`.

    **Current implementation:** Manual validation loop checking isinstance on each token/agent_id
    pair, raising generic ValueError on mismatch (auth.py, lines 60-69).

    **Problems:**
    1. Verbose hand-written isinstance checks
    2. Easy to miss edge cases (None, numbers)
    3. Poor error messages (generic ValueError without location)
    4. Not composable or reusable
    5. Incomplete validation of nested structure

    **The correct approach:**
    Use Pydantic's `TypeAdapter(dict[str, AgentID])` to validate and parse in one step.
    Can call `validate_python(data)` after `json.loads()` or `validate_json(text)` directly.

    **Benefits:**
    1. Automatic validation with better error messages showing exact path
    2. Type-safe: TypeAdapter knows the shape is `dict[str, AgentID]`
    3. Concise: 1 line instead of 10 lines of manual validation
    4. Robust: handles edge cases correctly
    5. Composable: can reuse the adapter elsewhere
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [60, 69],   // Manual isinstance validation loop
    ],
  },
)
