local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Fixture contains unnecessary variable and docstring.

    The `persistence` fixture in test_policy_resources.py lines 19-25 has:
    - Single-use variable `db_path` that should be inlined
    - Docstring that adds no value (function name and code are self-documenting)

    Should be simplified to:
    ```python
    @pytest.fixture
    async def persistence(tmp_path):
        persist = SQLitePersistence(tmp_path / "test.db")
        await persist.ensure_schema()
        return persist
    ```
  |||,
  filesToRanges={
    'adgn/tests/mcp/approval_policy/test_policy_resources.py': [[19, 25]],
  },
)
