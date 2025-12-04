local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 86-90 parse model_str with branching logic, but both branches call `.strip()`
    on the result. The stripping is common trunk that should be factored out.

    **Current:**
    ```python
    if ":" in model_str:
        _prefix, model_name = model_str.split(":", 1)
        model_name = model_name.strip()
    else:
        model_name = model_str.strip()
    ```

    **Simplified:**
    ```python
    if ":" in model_str:
        _prefix, model_str = model_str.split(":", 1)
    model_name = model_str.strip()
    ```

    Splits model_str if it has ":", then always strips the result.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [85, 90],  // Common trunk .strip() should be factored out
    ],
  },
)
