local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 743-744 extract `model_name` from config with a comment saying "Model parsing
    handled by AppConfig.resolve". Both the variable and comment are unnecessary.

    **Current:**
    ```python
    # Model parsing handled by AppConfig.resolve
    model_name = config.model_name

    # Later used at:
    key = build_cache_key(model_name, ...)  # line 752-753
    ProduceMessageInput(..., model_name=model_name, ...)  # line 759
    ```

    **Problems:**
    1. `model_name` is used only twice, both could use `config.model_name` directly
    2. Comment is useless - it's obvious that AppConfig.resolve handles parsing
    3. Extra variable to track for no benefit

    **Fix:**
    - Delete lines 743-744
    - Line 753: Use `config.model_name` instead of `model_name`
    - Line 759: Use `config.model_name` instead of `model_name`

    **Benefits:**
    1. Fewer variables
    2. Clear where value comes from (config)
    3. No useless comment
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [743, 744],  // Unnecessary variable and useless comment
      753,  // Use config.model_name
      759,  // Use config.model_name
    ],
  },
)
