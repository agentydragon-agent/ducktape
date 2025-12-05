local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The test contains low-value enum assertions that just duplicate production code definitions.

    **Current code (lines 149-150):**
    ```python
    @pytest.mark.asyncio
    async def test_token_role_enum(self):
        """Test TokenRole enum values."""
        assert TokenRole.HUMAN == "human"
        assert TokenRole.AGENT == "agent"

        # Test that enum can be created from string
        role = TokenRole("human")
        assert role == TokenRole.HUMAN
    ```

    **Why these assertions are low-value:**
    - Lines 149-150 just assert the enum values equal their string representations
    - This duplicates what's already in the production code definition
    - If someone changes the enum value, they'll see it immediately without needing a test
    - The assertions don't test any meaningful behavior

    **What should stay:**
    Lines 152-154 (testing enum construction from string) have value because they test
    actual behavior rather than just duplicating definitions. Keep these.

    **Recommended fix:**
    Delete assertions at lines 149-150. Keep the string-to-enum construction test (lines 152-154)
    as it verifies actual parsing behavior.
  |||,
  filesToRanges={
    'adgn/tests/agent/server/test_mcp_routing.py': [[149, 150]],
  },
)
