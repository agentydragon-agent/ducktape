local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    JUPYTER_CONFIG_STRATEGY.md specifies that JUPYTER_RUNTIME_DIR should be set to
    <run_root>/runtime (line 6), but launch.py's child_env (lines 111-114) only sets
    JUPYTER_PATH, JUPYTER_DATA_DIR, and JUPYTER_CONFIG_DIR, omitting JUPYTER_RUNTIME_DIR
    entirely. Without JUPYTER_RUNTIME_DIR set, Jupyter uses its default location:
    jupyter_data_dir() + "/runtime" (per jupyter_core/paths.py). Since child_env sets
    JUPYTER_DATA_DIR to <run_root>/data, Jupyter will use <run_root>/data/runtime for its
    runtime directory, not <run_root>/runtime as documented. This means jpserver-<pid>.json
    files (which contain server URL/token info) are written to <run_root>/data/runtime instead
    of <run_root>/runtime.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/sandboxed_jupyter/launch.py': [[111, 114]],
    'adgn/docs/llm/sandboxer/JUPYTER_CONFIG_STRATEGY.md': [[6, 6]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/mcp/sandboxed_jupyter/launch.py', 'adgn/docs/llm/sandboxer/JUPYTER_CONFIG_STRATEGY.md'],
  ],
)
