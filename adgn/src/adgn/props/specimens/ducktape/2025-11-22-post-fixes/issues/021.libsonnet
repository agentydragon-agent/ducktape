local I = import '../../specimens/lib.libsonnet';

// iss-021: Manual isinstance validation instead of Pydantic TypeAdapter

I.issueOneOccurrence(
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
  properties=['use-platform-primitives', 'declarative-validation'],
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/auth.py': [
      [60, 69],   // Manual isinstance validation loop
    ],
  },
  gap_note= |||
    This finding illustrates **"declarative-validation"**: prefer declarative schemas
    (Pydantic models, TypeAdapters) over imperative validation code (isinstance checks,
    manual loops).

    Declarative validation:
    - Describes WHAT the data should be (types, constraints)
    - Library handles HOW to validate
    - Produces structured, informative errors
    - Composable and reusable

    Imperative validation:
    - Describes HOW to check the data (if/isinstance/for loops)
    - You handle edge cases manually
    - Produces generic error messages
    - Hard to reuse or compose

    Related to "use-platform-primitives": Pydantic is the standard validation library
    in modern Python. Use its features instead of reinventing validation logic.

    When to use TypeAdapter:
    - Validating simple types (dict[str, int], list[Foo], etc.)
    - One-off validation without defining a full model
    - Loading config/data files with known structure
    - Parsing API responses into typed structures
  |||,
)
