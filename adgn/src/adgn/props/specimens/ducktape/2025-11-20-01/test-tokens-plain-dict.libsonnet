local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The `test_tokens` fixture uses plain dict instead of Pydantic model for type safety.

    **Current code (lines 15-21):**
    ```python
    @pytest.fixture
    def test_tokens():
        """Override the global TOKEN_TABLE for testing."""
        return {
            "test-human-token": {"role": "human"},
            "test-agent-token": {"role": "agent", "agent_id": "test-agent-1"},
            "test-invalid-role": {"role": "invalid"},
        }
    ```

    **Why this is problematic:**
    - Test data doesn't match production types (loses type safety)
    - Type errors only caught at runtime, not at test construction
    - Refactoring is unsafe (Pydantic model changes won't break tests immediately)
    - Structure is implicit rather than explicit

    **Recommended fix:**
    If there's a TokenConfig or similar Pydantic model in production code, the fixture
    should construct instances of that model:
    ```python
    @pytest.fixture
    def test_tokens():
        return {
            "test-human-token": TokenConfig(role="human"),
            "test-agent-token": TokenConfig(role="agent", agent_id="test-agent-1"),
            "test-invalid-role": TokenConfig(role="invalid"),
        }
    ```

    This ensures test data matches production types, catches errors early, and makes
    refactoring safer.
  |||,
  filesToRanges={
    'adgn/tests/agent/server/test_mcp_routing.py': [[15, 21]],
  },
)
