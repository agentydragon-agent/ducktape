local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Test file has unnecessary `__main__` block.

    Lines 153-154 in test_policy_validation_reload.py contain:
    ```python
    if __name__ == "__main__":
        pytest.main([__file__, "-v"])
    ```

    Pytest tests shouldn't have `__main__` blocks. Run with `pytest` command instead. This is an outdated pattern.
  |||,
  filesToRanges={
    'adgn/tests/agent/test_policy_validation_reload.py': [[153, 154]],
  },
)
