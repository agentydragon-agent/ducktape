local I = import '../../specimens/lib.libsonnet';

// iss-021: Manual isinstance validation instead of Pydantic TypeAdapter

I.issueOneOccurrence(
  rationale= |||
    The `reload()` method manually validates that the loaded JSON is a dict with string
    keys and values using `isinstance()` checks, but this can be done automatically and
    more robustly using Pydantic's `TypeAdapter`.

    **Current implementation (auth.py, lines 60-69):**
    ```python
    def reload(self) -> None:
        """Reload mapping from file."""
        if not self.path.exists():
            raise FileNotFoundError(f"Token mapping file not found: {self.path}")

        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Token mapping must be a JSON object")

        # Validate all values are strings and convert to AgentID
        mapping: dict[str, AgentID] = {}
        for token, agent_id in data.items():
            if not isinstance(token, str) or not isinstance(agent_id, str):
                raise ValueError(f"Invalid mapping: {token} -> {agent_id}")
            mapping[token] = AgentID(agent_id)

        self._mapping = mapping
    ```

    **Problems:**

    1. **Manual validation**: Hand-written isinstance checks are verbose
    2. **Error-prone**: Easy to forget edge cases (None, numbers that JSON accepts)
    3. **Poor error messages**: Generic ValueError doesn't say what's wrong where
    4. **Not composable**: Can't reuse validation logic
    5. **Incomplete**: Doesn't validate dict structure deeply (nested types, etc.)

    **The correct approach:**

    Use Pydantic's `TypeAdapter` to validate and parse in one step:

    ```python
    from pydantic import TypeAdapter

    # At module level:
    TokenMappingAdapter = TypeAdapter(dict[str, AgentID])

    def reload(self) -> None:
        """Reload mapping from file."""
        if not self.path.exists():
            raise FileNotFoundError(f"Token mapping file not found: {self.path}")

        data = json.loads(self.path.read_text())
        # Validate and convert in one step
        self._mapping = TokenMappingAdapter.validate_python(data)
        logger.info(f"Loaded {len(self._mapping)} token mappings from {self.path}")
    ```

    Or even more concise with direct JSON validation:
    ```python
    def reload(self) -> None:
        """Reload mapping from file."""
        if not self.path.exists():
            raise FileNotFoundError(f"Token mapping file not found: {self.path}")

        # Parse and validate JSON in one step
        self._mapping = TokenMappingAdapter.validate_json(self.path.read_text())
        logger.info(f"Loaded {len(self._mapping)} token mappings from {self.path}")
    ```

    **Benefits:**

    1. **Automatic validation**: Pydantic checks all types automatically
    2. **Better errors**: ValidationError shows exact path and problem
    3. **Type-safe**: TypeAdapter knows the shape is `dict[str, AgentID]`
    4. **Concise**: 1 line instead of 10 lines of validation
    5. **Robust**: Handles edge cases (None, numbers, nested objects) correctly

    **Example error messages:**

    Manual approach:
    ```
    ValueError: Invalid mapping: some_token -> 123
    ```

    Pydantic approach:
    ```
    ValidationError: 1 validation error for dict[str, AgentID]
    some_token
      Input should be a valid string [type=string_type, input_value=123]
    ```

    Much more informative!

    **Note on AgentID:**

    If `AgentID` is a simple string wrapper (like `AgentID = NewType("AgentID", str)`),
    Pydantic will handle the conversion automatically. If it's a custom class, make
    sure it's a Pydantic model or has a validator.
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
