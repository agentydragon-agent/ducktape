local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The code defines two enums, `PolicyErrorCode` and `PolicyErrorStage`, which are
    subset-related and redundant. `PolicyErrorCode` has values `READ_ERROR` and
    `PARSE_ERROR`, while `PolicyErrorStage` has `READ`, `PARSE`, and `TESTS`.

    The error code is always derived from the stage (just add `_ERROR` suffix), so
    having both enums is unnecessary duplication.

    **Current implementation (policy_error.py, lines 9-17):**
    ```python
    class PolicyErrorCode(StrEnum):
        READ_ERROR = "read_error"
        PARSE_ERROR = "parse_error"


    class PolicyErrorStage(StrEnum):
        READ = "read"
        PARSE = "parse"
        TESTS = "tests"


    class PolicyError(BaseModel):
        stage: PolicyErrorStage = Field(description="Processing stage where error occurred")
        code: PolicyErrorCode = Field(description="Error code (read_error, parse_error)")
        index: int | None = Field(None, description="Character/token index where error occurred")
        length: int | None = Field(None, description="Length of error span in characters/tokens")
        message: str | None = Field(None, description="Human-readable error message")
    ```

    **Problems:**

    1. **Redundant enums**: `code` is always `stage + "_error"`
    2. **Maintenance burden**: Must keep two enums in sync when adding stages
    3. **Missing value**: `TESTS` stage has no corresponding error code
    4. **Confusing**: Why have both when one fully determines the other?
    5. **Type mismatch**: `PolicyError` has both fields but they're always redundant

    **The correct approach:**

    Keep only `PolicyErrorStage` and add a `TESTS_ERROR` value if needed:

    ```python
    class PolicyErrorStage(StrEnum):
        READ = "read"
        PARSE = "parse"
        TESTS = "tests"


    class PolicyError(BaseModel):
        stage: PolicyErrorStage = Field(description="Processing stage where error occurred")
        # Remove 'code' field entirely - it's redundant with 'stage'
        index: int | None = Field(None, description="Character/token index where error occurred")
        length: int | None = Field(None, description="Length of error span in characters/tokens")
        message: str | None = Field(None, description="Human-readable error message")
    ```

    Or if you need the `code` field for backwards compatibility or API contracts:

    ```python
    class PolicyErrorStage(StrEnum):
        READ = "read"
        PARSE = "parse"
        TESTS = "tests"


    class PolicyError(BaseModel):
        stage: PolicyErrorStage = Field(description="Processing stage where error occurred")
        index: int | None = Field(None, description="Character/token index where error occurred")
        length: int | None = Field(None, description="Length of error span in characters/tokens")
        message: str | None = Field(None, description="Human-readable error message")

        @property
        def code(self) -> str:
            """Derive error code from stage (for backwards compatibility)."""
            return f"{self.stage}_error"

        model_config = ConfigDict(extra="forbid")
    ```

    Or merge both into a single unified enum:

    ```python
    class PolicyError(StrEnum):
        """Unified policy error types combining stage and code."""
        READ_ERROR = "read_error"
        PARSE_ERROR = "parse_error"
        TESTS_ERROR = "tests_error"  # Add missing tests error


    class PolicyErrorDetails(BaseModel):
        """Details about a policy processing error."""
        error_type: PolicyError = Field(description="Error type")
        index: int | None = Field(None, description="Character/token index where error occurred")
        length: int | None = Field(None, description="Length of error span in characters/tokens")
        message: str | None = Field(None, description="Human-readable error message")

        model_config = ConfigDict(extra="forbid")
    ```

    **Benefits:**

    1. **No duplication**: One enum instead of two redundant ones
    2. **Easier to maintain**: Adding a new stage doesn't require updating two enums
    3. **Clearer model**: No redundant fields in `PolicyError`
    4. **Type safety**: Can't accidentally mismatch stage and code
    5. **Complete coverage**: TESTS stage now has a corresponding error variant

    **Migration path:**

    1. Update all code that constructs `PolicyError` to not set `code`
    2. Add `@property def code()` if needed for compatibility
    3. Remove `PolicyErrorCode` enum
    4. Add `TESTS` to unified enum if using the merged approach
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/models/policy_error.py': [
      [9, 11],   // PolicyErrorCode enum (redundant)
      [14, 17],  // PolicyErrorStage enum
      [21, 22],  // PolicyError with both stage and code fields
    ],
  },
)
